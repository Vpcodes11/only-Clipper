"""
Main FastAPI Application — Production Pipeline with resumable staged queue.
Exposes REST endpoints, static file hosting for previewing clips,
and in-memory WebSockets for live status & execution log streaming.
"""
import os
import re
import uuid
import math
import shutil
import logging
import asyncio
import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor

from api.database import SessionLocal, init_db
from api.models import Job, Clip, ClipAnalytics
from sqlalchemy import func as sa_func
from services.storage import get_storage
from services.ffmpeg import PRESETS, CAPTION_STYLES
from workers.task_processor import (
    subscribe_to_progress,
    dispatch_progress,
    STAGE_COMPLETE,
    STAGE_ERROR,
)
from workers.job_queue import enqueue_stage, resume_job, get_queue_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

STORAGE_DIR = os.path.abspath(os.getenv("STORAGE_DIR", "./storage"))
TEMP_DIR = os.path.abspath(os.getenv("TEMP_DIR", "./temp"))
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "4096"))
STUCK_JOB_THRESHOLD_SECONDS = int(os.getenv("STUCK_JOB_THRESHOLD_SECONDS", "600"))

app = FastAPI(title="Only Clipper API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    _event_loop = asyncio.get_running_loop()
    init_db()
    os.makedirs(STORAGE_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    cleanup_orphaned_dirs()
    recover_stuck_jobs()
    # Start Redis progress listener
    from workers.task_processor import start_redis_progress_listener
    start_redis_progress_listener()
    # Start WebSocket heartbeat (fix #19)
    asyncio.create_task(_ws_heartbeat())


STATIC_DIR = STORAGE_DIR
app.mount("/storage", StaticFiles(directory=STATIC_DIR), name="storage")

active_connections = {}
_ws_lock = asyncio.Lock()
_event_loop = None  # Captured at startup


async def _ws_heartbeat():
    """Periodically ping WebSocket connections; remove dead ones."""
    while True:
        await asyncio.sleep(30)
        async with _ws_lock:
            for job_id in list(active_connections.keys()):
                sockets = active_connections.get(job_id, [])
                alive = []
                for ws in sockets:
                    try:
                        await ws.send_json({"type": "ping"})
                        alive.append(ws)
                    except Exception:
                        pass
                if alive:
                    active_connections[job_id] = alive
                else:
                    del active_connections[job_id]


def _save_event_loop():
    global _event_loop
    if _event_loop is None:
        try:
            _event_loop = asyncio.get_running_loop()
        except RuntimeError:
            _event_loop = asyncio.get_event_loop()
    return _event_loop


async def broadcast_to_job_websockets(job_id: str, data: dict):
    async with _ws_lock:
        sockets = active_connections.get(job_id, [])
    for ws in list(sockets):
        try:
            await ws.send_json(data)
        except Exception:
            async with _ws_lock:
                try:
                    active_connections.get(job_id, []).remove(ws)
                except (ValueError, KeyError):
                    pass


def ws_progress_dispatcher(job_id: str, data: dict):
    loop = _save_event_loop()
    if loop and loop.is_running():
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(broadcast_to_job_websockets(job_id, data))
        )


subscribe_to_progress(ws_progress_dispatcher)


# ─── Startup Recovery ─────────────────────────────────────────────


def cleanup_orphaned_dirs():
    """Clean up storage/temp dirs for jobs that no longer exist in the DB."""
    db = SessionLocal()
    try:
        active_job_ids = {row[0] for row in db.query(Job.id).all()}
    finally:
        db.close()

    if os.path.isdir(TEMP_DIR):
        for entry in os.listdir(TEMP_DIR):
            path = os.path.join(TEMP_DIR, entry)
            if os.path.isdir(path) and entry not in active_job_ids and entry != "work":
                try:
                    shutil.rmtree(path, ignore_errors=True)
                    logger.info("Cleaned orphaned temp dir: %s", path)
                except Exception as e:
                    logger.warning("Failed to clean temp dir %s: %s", path, e)

    if os.path.isdir(STORAGE_DIR):
        reserved_storage_dirs = {"cache", "clips", "thumbnails", "sources"}
        for entry in os.listdir(STORAGE_DIR):
            path = os.path.join(STORAGE_DIR, entry)
            if os.path.isdir(path) and entry not in active_job_ids and entry not in reserved_storage_dirs:
                db = SessionLocal()
                try:
                    still_active = db.query(Job).filter(Job.id == entry).first()
                    if not still_active:
                        shutil.rmtree(path, ignore_errors=True)
                        logger.info("Cleaned orphaned storage dir: %s", path)
                except Exception as e:
                    logger.warning("Failed to clean storage dir %s: %s", path, e)
                finally:
                    db.close()


def recover_stuck_jobs():
    """On startup, find stuck jobs and resume them from their last stage."""
    db = SessionLocal()
    try:
        stuck = db.query(Job).filter(
            Job.status.in_(["processing", "queued"]),
            Job.stage != "export_completed",
            Job.stage != "failed",
        ).all()

        for job in stuck:
            if job.stage_started_at:
                age = (datetime.datetime.now(datetime.UTC) - job.stage_started_at.replace(tzinfo=datetime.UTC)).total_seconds()
                if age > STUCK_JOB_THRESHOLD_SECONDS:
                    logger.warning("Recovering stuck job %s at stage %s (%.0fs old)", job.id, job.stage, age)
                    try:
                        resume_job(job.id)
                    except Exception as e:
                        logger.warning("Could not enqueue recovery for job %s: %s", job.id, e)
                else:
                    logger.info("Job %s recently started (%.0fs). Skipping recovery.", job.id, age)
            else:
                try:
                    resume_job(job.id)
                except Exception as e:
                    logger.warning("Could not enqueue recovery for job %s: %s", job.id, e)
    finally:
        db.close()


# ─── DB Session ───────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_thread_pool = ThreadPoolExecutor(max_workers=4)


async def _async_db_query(sync_func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_thread_pool, lambda: sync_func(*args, **kwargs))


class WordUpdate(BaseModel):
    word: str
    start: float
    end: float


class EditClipRequest(BaseModel):
    job_id: str
    filename: Optional[str] = None
    clip_id: Optional[str] = None
    title: str
    hook_caption: str
    words: List[WordUpdate]
    caption_style: Optional[str] = None
    preset: Optional[str] = None


def is_valid_url(url: str) -> bool:
    patterns = [
        r"https?://(www\.)?youtube\.com/watch",
        r"https?://youtu\.be/",
        r"https?://(www\.)?twitch\.tv/",
        r"https?://(www\.)?vimeo\.com/",
        r"https?://(www\.)?dailymotion\.com/",
        r"https?://.+\.(mp4|mkv|mov|avi|webm)",
    ]
    return any(re.match(p, url, re.IGNORECASE) for p in patterns)


# ─── Endpoints ──────────────────────────────────────────────────


def _serialize_clip(c: Clip, storage=None) -> dict:
    storage = storage or get_storage()
    return {
        "id": c.id,
        "clip_id": c.id,
        "job_id": c.job_id,
        "filename": c.filename,
        "title": c.title,
        "hook_caption": c.hook_caption,
        "virality_score": c.virality_score,
        "reason": c.reason,
        "category": c.category,
        "hashtags": c.hashtags or [],
        "start_time": c.start_time,
        "end_time": c.end_time,
        "duration": c.duration,
        "status": c.status,
        "words": c.words or [],
        "render_version": c.render_version or 0,
        "storage_path": c.storage_path,
        "thumbnail_path": c.thumbnail_path,
        "url": storage.get_url(c.storage_path) if c.storage_path else None,
        "thumbnail_url": storage.get_url(c.thumbnail_path) if c.thumbnail_path else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _job_clip_payload(job: Job, db: Session) -> list:
    storage = get_storage()
    rows = (
        db.query(Clip)
        .filter(Clip.job_id == job.id, Clip.status != "deleted")
        .order_by(Clip.created_at.asc())
        .all()
    )
    if rows:
        return [_serialize_clip(c, storage) for c in rows]

    result = []
    for c in job.clips or []:
        entry = dict(c)
        clip_id = entry.get("clip_id") or entry.get("id")
        if clip_id:
            entry["id"] = clip_id
            entry["clip_id"] = clip_id
            entry["job_id"] = job.id
            storage_path = entry.get("storage_path") or entry.get("storage_key") or f"clips/{job.id}/{clip_id}.mp4"
            thumb_path = entry.get("thumbnail_path") or f"thumbnails/{job.id}/{clip_id}.jpg"
            entry["storage_path"] = storage_path
            entry["thumbnail_path"] = thumb_path
            entry["url"] = storage.get_url(storage_path)
            entry["thumbnail_url"] = storage.get_url(thumb_path)
        result.append(entry)
    return result


@app.get("/api/presets")
async def get_presets():
    return JSONResponse({
        "presets": PRESETS,
        "caption_styles": {k: {"name": k.replace("_", " ").title(), "label": k.replace("_", " ").title()} for k in CAPTION_STYLES},
    })


@app.get("/api/jobs")
async def get_jobs(db: Session = Depends(get_db)):
    def _fetch():
        jobs = db.query(Job).order_by(Job.created_at.desc()).all()
        result = []
        for j in jobs:
            result.append({
                "id": j.id,
                "status": j.status,
                "progress": j.progress,
                "message": j.message,
                "stage": j.stage,
                "source": j.source,
                "preset": j.preset,
                "caption_style": j.caption_style,
                "clips": _job_clip_payload(j, db),
                "retry_count": j.retry_count,
                "max_retries": j.max_retries,
                "stage_timings": j.stage_timings,
                "download_quality": j.download_quality,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            })
        return result
    return await _async_db_query(_fetch)


@app.get("/api/status/{job_id}")
async def get_status(job_id: str, db: Session = Depends(get_db)):
    def _fetch():
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return JSONResponse({
            "id": job.id,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "message": job.message,
            "source": job.source,
            "clips": _job_clip_payload(job, db),
            "transcript": job.transcript,
            "errors": job.errors or [],
            "retry_count": job.retry_count,
            "max_retries": job.max_retries,
            "stage_timings": job.stage_timings,
            "stage_started_at": job.stage_started_at.isoformat() if job.stage_started_at else None,
            "download_quality": job.download_quality,
        })
    return await _async_db_query(_fetch)


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str, db: Session = Depends(get_db)):
    def _delete():
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        storage = get_storage()
        for clip in (job.clips or []):
            clip_id = clip.get("clip_id")
            if clip_id:
                storage.delete(f"clips/{job_id}/{clip_id}.mp4")
                storage.delete(f"thumbnails/{job_id}/{clip_id}.jpg")
        for clip_row in job.rendered_clips:
            db.delete(clip_row)
        db.delete(job)
        db.commit()
        storage_dir = os.path.join(STORAGE_DIR, job_id)
        if os.path.exists(storage_dir):
            shutil.rmtree(storage_dir, ignore_errors=True)
        temp_dir = os.path.join(TEMP_DIR, job_id)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        return {"success": True}
    return await _async_db_query(_delete)


@app.post("/api/job/{job_id}/resume")
async def resume_endpoint(job_id: str, db: Session = Depends(get_db)):
    def _resume():
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(404, "Job not found")
        if job.stage == "export_completed":
            return {"status": "already_complete"}
        job.status = "processing"
        job.retry_count = 0
        job.message = "Resuming pipeline..."
        db.commit()
        result = resume_job(job_id)
        if result:
            return {"status": "resuming", "stage": job.stage, "rq_job_id": result.id}
        return {"status": "queued", "stage": job.stage}
    return await _async_db_query(_resume)


@app.get("/api/metrics")
async def get_metrics():
    def _fetch():
        try:
            queue_stats = get_queue_stats()
        except Exception as e:
            queue_stats = {"error": str(e)}
        db = SessionLocal()
        try:
            total = db.query(Job).count()
            processing = db.query(Job).filter(Job.status == "processing").count()
            complete = db.query(Job).filter(Job.status == "complete").count()
            failed = db.query(Job).filter(Job.status.in_(["error", "failed"])).count()
        finally:
            db.close()
        return {
            "jobs": {"total": total, "processing": processing, "complete": complete, "failed": failed},
            "queues": queue_stats,
        }
    return await _async_db_query(_fetch)


@app.post("/api/upload")
async def upload_video(
    file: UploadFile = File(None),
    url: str = Form(None),
    provider: str = Form("groq"),
    preset: str = Form("tiktok"),
    caption_style: str = Form("typography_motion"),
    quality: str = Form("proxy"),
    db: Session = Depends(get_db),
):
    """Accepts local video file upload or remote URL. Enqueues to staged pipeline."""
    job_id = str(uuid.uuid4())[:8]
    storage_dir = os.path.join(STORAGE_DIR, job_id)
    os.makedirs(storage_dir, exist_ok=True)

    video_path = os.path.join(storage_dir, "source.mp4")
    source_name = ""
    start_stage = "job_created"

    if url and url.strip():
        clean_url = url.strip()
        if not is_valid_url(clean_url):
            raise HTTPException(status_code=400, detail="Invalid video URL.")
        source_name = clean_url
        start_stage = "download_started"

    elif file:
        source_name = file.filename
        max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
        total = 0
        try:
            with open(video_path, "wb") as f:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        f.close()
                        os.remove(video_path)
                        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_SIZE_MB}MB limit")
                    f.write(chunk)
        except HTTPException:
            raise
        except Exception as e:
            if os.path.exists(video_path):
                os.remove(video_path)
            raise HTTPException(status_code=500, detail=f"File save failed: {e}")
        start_stage = "metadata_fetched"
    else:
        raise HTTPException(status_code=400, detail="Must provide file or URL.")

    new_job = Job(
        id=job_id,
        status="queued",
        stage="job_created",
        video_path=video_path,
        provider=provider,
        preset=preset,
        caption_style=caption_style,
        download_quality=quality,
        message="Initializing pipeline...",
        source=source_name,
        clips=[],
        errors=[],
        progress=0,
    )
    db.add(new_job)
    db.commit()

    try:
        enqueue_stage(job_id, start_stage)
    except Exception as e:
        logger.warning("Failed to enqueue job %s (Redis unavailable?): %s", job_id, e)
        new_job.status = "queued"
        new_job.message = "Job created but queue unavailable. Start Redis to process."
        new_job.stage = "queued"
        db.commit()

    return JSONResponse({"job_id": job_id, "stage": start_stage})


@app.post("/api/clip/edit")
async def edit_clip(req: EditClipRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Regenerates a clip's captions asynchronously. Atomically replaces output."""
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Project not found")
    if job.status == "processing":
        raise HTTPException(409, "Video compile in progress. Please wait.")

    clip_q = db.query(Clip).filter(Clip.job_id == req.job_id)
    if req.clip_id:
        clip_q = clip_q.filter(Clip.id == req.clip_id)
    elif req.filename:
        clip_q = clip_q.filter(Clip.filename == req.filename)
    else:
        raise HTTPException(400, "clip_id or filename is required")

    clip_row = clip_q.first()
    if not clip_row:
        raise HTTPException(404, "Clip not found")
    if not clip_row.storage_path:
        raise HTTPException(404, "Clip media is not available in persistent storage")

    target_clip = _serialize_clip(clip_row)
    clip_idx = max(0, db.query(Clip).filter(Clip.job_id == req.job_id, Clip.created_at < clip_row.created_at).count())

    words_list = [{"word": w.word, "start": w.start, "end": w.end} for w in req.words]

    def regenerate_clip_task():
        db_task = SessionLocal()
        temp_output_path = None
        try:
            job_task = db_task.query(Job).filter(Job.id == req.job_id).first()
            if not job_task:
                return
            job_task.status = "processing"
            job_task.stage = "clip_regenerating"
            job_task.message = f"Regenerating: {req.title}..."
            db_task.commit()

            dispatch_progress(req.job_id, {"type": "progress", "message": job_task.message, "progress": 90})

            clip_task = db_task.query(Clip).filter(Clip.id == target_clip["id"]).first()
            if not clip_task:
                raise RuntimeError("Clip record disappeared before render")
            if not job_task.video_path or not os.path.exists(job_task.video_path):
                source_key = (job_task.checkpoint_data or {}).get("source_storage_path")
                if not source_key:
                    raise RuntimeError("Source video is unavailable; cannot re-render this clip")
                restored_source = os.path.join(TEMP_DIR, req.job_id, "source.mp4")
                get_storage().download(source_key, restored_source)
                job_task.video_path = restored_source
                db_task.commit()

            output_dir = os.path.join(TEMP_DIR, req.job_id, "renders")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, clip_task.filename)
            temp_output_path = f"{output_path}.tmp-{uuid.uuid4().hex}.mp4"

            clip_info = {
                "start_time": target_clip["start_time"],
                "end_time": target_clip["end_time"],
                "title": req.title,
                "hook_caption": req.hook_caption,
            }
            style = req.caption_style or job_task.caption_style
            preset_choice = req.preset or job_task.preset

            from services.ffmpeg import safe_create_clip
            result = safe_create_clip(
                video_path=job_task.video_path,
                clip_info=clip_info,
                words=words_list,
                output_path=temp_output_path,
                clip_index=clip_idx,
                caption_style=style,
                preset=preset_choice,
            )
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "FFmpeg clip compile failed"))

            if os.path.exists(temp_output_path):
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.replace(temp_output_path, output_path)

            storage = get_storage()
            storage.upload(output_path, clip_task.storage_path, "video/mp4")
            clip_task.title = req.title
            clip_task.hook_caption = req.hook_caption
            clip_task.words = words_list
            clip_task.content_hash = storage.compute_hash(output_path)
            clip_task.render_version = (clip_task.render_version or 0) + 1
            clip_task.updated_at = datetime.datetime.now(datetime.UTC)

            updated_clips = [_serialize_clip(c, storage) for c in (
                db_task.query(Clip)
                .filter(Clip.job_id == req.job_id, Clip.status != "deleted")
                .order_by(Clip.created_at.asc())
                .all()
            )]
            job_task.clips = updated_clips
            job_task.status = "complete"
            job_task.stage = STAGE_COMPLETE
            job_task.message = "Clip re-rendered successfully!"
            job_task.progress = 100
            db_task.commit()

            dispatch_progress(req.job_id, {
                "type": "complete", "message": job_task.message,
                "clips": updated_clips, "transcript": job_task.transcript,
            })
        except Exception as e:
            logger.exception("Clip edit failed")
            if temp_output_path and os.path.exists(temp_output_path):
                try:
                    os.remove(temp_output_path)
                except OSError:
                    pass
            job_err = db_task.query(Job).filter(Job.id == req.job_id).first()
            if job_err:
                errors = list(job_err.errors or [])
                errors.append({"stage": "edit", "message": str(e)})
                job_err.errors = errors
                job_err.status = "error"
                job_err.stage = STAGE_ERROR
                job_err.message = f"Edit failed: {e}"
                db_task.commit()
            dispatch_progress(req.job_id, {"type": "error", "message": f"Edit failed: {e}"})
        finally:
            db_task.close()

    background_tasks.add_task(regenerate_clip_task)
    return {"status": "processing", "message": "Caption re-render scheduled."}


# ─── Clip Library Endpoints ──────────────────────────────────────


@app.get("/api/clips")
async def get_clips(
    page: int = 1,
    per_page: int = 20,
    status: str = "active",
    job_id: str = None,
    sort: str = "created_at_desc",
    search: str = None,
    db: Session = Depends(get_db),
):
    def _fetch():
        q = db.query(Clip)
        if status and status != "all":
            q = q.filter(Clip.status == status)
        if job_id:
            q = q.filter(Clip.job_id == job_id)
        if search:
            q = q.filter(Clip.title.ilike(f"%{search}%"))
        if sort == "virality_score_desc":
            q = q.order_by(Clip.virality_score.desc())
        elif sort == "duration_asc":
            q = q.order_by(Clip.duration.asc())
        elif sort == "created_at_asc":
            q = q.order_by(Clip.created_at.asc())
        else:
            q = q.order_by(Clip.created_at.desc())
        total = q.count()
        per_page_clamped = min(max(per_page, 1), 100)
        offset = (page - 1) * per_page_clamped
        clips = q.offset(offset).limit(per_page_clamped).all()
        storage = get_storage()
        result = [_serialize_clip(c, storage) for c in clips]
        return {
            "clips": result, "total": total, "page": page,
            "per_page": per_page_clamped,
            "pages": max(1, (total + per_page_clamped - 1) // per_page_clamped),
        }
    return await _async_db_query(_fetch)


@app.get("/api/clips/{clip_id}")
async def get_clip(clip_id: str, db: Session = Depends(get_db)):
    def _fetch():
        c = db.query(Clip).filter(Clip.id == clip_id).first()
        if not c:
            raise HTTPException(404, "Clip not found")
        return _serialize_clip(c)
    return await _async_db_query(_fetch)


@app.get("/api/clips/{clip_id}/download")
async def download_clip(clip_id: str, db: Session = Depends(get_db)):
    def _fetch():
        c = db.query(Clip).filter(Clip.id == clip_id).first()
        if not c:
            raise HTTPException(404, "Clip not found")
        if not c.storage_path:
            raise HTTPException(404, "Clip file not available")
        from fastapi.responses import RedirectResponse
        url = get_storage().get_url(c.storage_path)
        return RedirectResponse(url=url)
    return await _async_db_query(_fetch)


@app.post("/api/clips/{clip_id}/archive")
async def archive_clip(clip_id: str, db: Session = Depends(get_db)):
    def _archive():
        c = db.query(Clip).filter(Clip.id == clip_id).first()
        if not c:
            raise HTTPException(404, "Clip not found")
        c.status = "archived"
        c.updated_at = datetime.datetime.now(datetime.UTC)
        db.commit()
        return {"status": "archived", "id": clip_id}
    return await _async_db_query(_archive)


@app.post("/api/clips/{clip_id}/restore")
async def restore_clip(clip_id: str, db: Session = Depends(get_db)):
    def _restore():
        c = db.query(Clip).filter(Clip.id == clip_id).first()
        if not c:
            raise HTTPException(404, "Clip not found")
        c.status = "active"
        c.updated_at = datetime.datetime.now(datetime.UTC)
        db.commit()
        return {"status": "active", "id": clip_id}
    return await _async_db_query(_restore)


@app.delete("/api/clips/{clip_id}")
async def delete_clip(clip_id: str, db: Session = Depends(get_db)):
    def _delete():
        c = db.query(Clip).filter(Clip.id == clip_id).first()
        if not c:
            raise HTTPException(404, "Clip not found")
        storage = get_storage()
        if c.storage_path:
            storage.delete(c.storage_path)
        if c.thumbnail_path:
            storage.delete(c.thumbnail_path)
        c.status = "deleted"
        c.storage_path = None
        c.thumbnail_path = None
        c.updated_at = datetime.datetime.now(datetime.UTC)
        db.commit()
        return {"status": "deleted", "id": clip_id}
    return await _async_db_query(_delete)


@app.post("/api/clips/{clip_id}/retry")
async def retry_clip_render(clip_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    c = db.query(Clip).filter(Clip.id == clip_id).first()
    if not c:
        raise HTTPException(404, "Clip not found")
    job = db.query(Job).filter(Job.id == c.job_id).first()
    if not job:
        raise HTTPException(404, "Parent job not found")
    if not job.transcript or not job.video_path:
        raise HTTPException(400, "Source transcript or video missing, cannot retry")

    c.render_version = (c.render_version or 0) + 1
    c.status = "active"
    c.updated_at = datetime.datetime.now(datetime.UTC)
    db.commit()

    def retry_render():
        db_task = SessionLocal()
        try:
            clip = db_task.query(Clip).filter(Clip.id == clip_id).first()
            job_task = db_task.query(Job).filter(Job.id == clip.job_id).first()
            if not clip or not job_task:
                return

            storage_dir = os.path.join(STORAGE_DIR, job_task.id)
            os.makedirs(storage_dir, exist_ok=True)
            output_path = os.path.join(storage_dir, clip.filename)

            clip_info = {
                "start_time": clip.start_time,
                "end_time": clip.end_time,
                "title": clip.title,
                "hook_caption": clip.hook_caption or clip.title,
            }

            from services.ffmpeg import safe_create_clip
            result = safe_create_clip(
                video_path=job_task.video_path,
                clip_info=clip_info,
                words=job_task.transcript.get("words", []),
                output_path=output_path,
                clip_index=0,
                caption_style=job_task.caption_style or "typography_motion",
                preset=job_task.preset or "tiktok",
            )

            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Retry render failed"))

            storage = get_storage()
            clip_key = f"clips/{job_task.id}/{clip.id}.mp4"
            thumb_path = os.path.join(storage_dir, os.path.splitext(clip.filename)[0] + ".jpg")

            storage.upload(output_path, clip_key, "video/mp4")
            if os.path.exists(thumb_path):
                thumb_key = f"thumbnails/{job_task.id}/{clip.id}.jpg"
                storage.upload(thumb_path, thumb_key, "image/jpeg")
                clip.thumbnail_path = thumb_key

            clip.storage_path = clip_key
            clip.content_hash = storage.compute_hash(output_path)
            clip.updated_at = datetime.datetime.now(datetime.UTC)
            db_task.commit()

            dispatch_progress(job_task.id, {
                "type": "clip_retry_complete",
                "clip_id": clip.id,
                "message": f"Clip '{clip.title}' re-rendered successfully",
            })
        except Exception as e:
            logger.exception("Clip retry failed for %s", clip_id)
            dispatch_progress(clip_id, {"type": "error", "message": f"Retry failed: {e}"})
        finally:
            db_task.close()

    background_tasks.add_task(retry_render)
    return {"status": "retrying", "id": clip_id}


# ─── Behavioral Feedback Collection ──────────────────────────

def _get_or_create_analytics(clip_id: str, db: Session) -> ClipAnalytics:
    analytics = db.query(ClipAnalytics).filter(ClipAnalytics.clip_id == clip_id).first()
    if not analytics:
        analytics = ClipAnalytics(clip_id=clip_id)
        db.add(analytics)
        db.flush()
    return analytics


def _record_interaction(analytics: ClipAnalytics, event_type: str, data: dict = None):
    history = list(analytics.interaction_history or [])
    history.append({
        "type": event_type,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "data": data or {},
    })
    if len(history) > 500:
        logger.warning("Interaction history truncated to 500 entries for clip %s", analytics.clip_id)
        history = history[-500:]
    analytics.interaction_history = history
    analytics.last_interaction = datetime.datetime.now(datetime.UTC)


@app.post("/api/clips/{clip_id}/feedback/view")
async def record_view(clip_id: str, watch_ms: int = 0, db: Session = Depends(get_db)):
    if watch_ms < 0:
        watch_ms = 0
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.preview_views = (analytics.preview_views or 0) + 1
    analytics.preview_total_watch_ms = (analytics.preview_total_watch_ms or 0) + watch_ms
    if analytics.preview_views > 0:
        analytics.avg_watch_duration_ms = analytics.preview_total_watch_ms // analytics.preview_views
    _record_interaction(analytics, "view", {"watch_ms": watch_ms})
    db.commit()
    return {"views": analytics.preview_views, "avg_watch_ms": analytics.avg_watch_duration_ms}


@app.post("/api/clips/{clip_id}/feedback/download")
async def record_download(clip_id: str, db: Session = Depends(get_db)):
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.downloads = (analytics.downloads or 0) + 1
    _record_interaction(analytics, "download")
    db.commit()
    return {"downloads": analytics.downloads}


@app.post("/api/clips/{clip_id}/feedback/export")
async def record_export(clip_id: str, db: Session = Depends(get_db)):
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.exports = (analytics.exports or 0) + 1
    _record_interaction(analytics, "export")
    db.commit()
    return {"exports": analytics.exports}


@app.post("/api/clips/{clip_id}/feedback/favorite")
async def record_favorite(clip_id: str, db: Session = Depends(get_db)):
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.favorites = (analytics.favorites or 0) + 1
    _record_interaction(analytics, "favorite")
    db.commit()
    return {"favorites": analytics.favorites}


@app.post("/api/clips/{clip_id}/feedback/share")
async def record_share(clip_id: str, db: Session = Depends(get_db)):
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.shares = (analytics.shares or 0) + 1
    _record_interaction(analytics, "share")
    db.commit()
    return {"shares": analytics.shares}


@app.post("/api/clips/{clip_id}/feedback/reject")
async def record_reject(clip_id: str, reason: str = "", db: Session = Depends(get_db)):
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.rejects = (analytics.rejects or 0) + 1
    _record_interaction(analytics, "reject", {"reason": reason[:200]})
    db.commit()
    return {"rejects": analytics.rejects}


@app.post("/api/clips/{clip_id}/feedback/regenerate")
async def record_regeneration(clip_id: str, db: Session = Depends(get_db)):
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.regenerations = (analytics.regenerations or 0) + 1
    _record_interaction(analytics, "regenerate")
    db.commit()
    return {"regenerations": analytics.regenerations}


@app.post("/api/clips/{clip_id}/feedback/boundary_edit")
async def record_boundary_edit(clip_id: str, db: Session = Depends(get_db)):
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.boundary_edits = (analytics.boundary_edits or 0) + 1
    _record_interaction(analytics, "boundary_edit")
    db.commit()
    return {"boundary_edits": analytics.boundary_edits}


@app.post("/api/clips/{clip_id}/feedback/rate")
async def record_rating(clip_id: str, rating: float = 0.0, db: Session = Depends(get_db)):
    if not math.isfinite(rating) or rating < 0 or rating > 5:
        raise HTTPException(400, "Rating must be between 0 and 5")
    analytics = _get_or_create_analytics(clip_id, db)
    analytics.user_rating = rating
    _record_interaction(analytics, "rate", {"rating": rating})
    db.commit()
    return {"rating": analytics.user_rating}


@app.get("/api/clips/{clip_id}/analytics")
async def get_clip_analytics(clip_id: str, db: Session = Depends(get_db)):
    def _fetch():
        analytics = db.query(ClipAnalytics).filter(ClipAnalytics.clip_id == clip_id).first()
        if not analytics:
            return {
                "preview_views": 0, "downloads": 0, "exports": 0,
                "favorites": 0, "shares": 0, "rejects": 0,
                "regenerations": 0, "boundary_edits": 0,
            }
        return {
            "preview_views": analytics.preview_views or 0,
            "preview_total_watch_ms": analytics.preview_total_watch_ms or 0,
            "avg_watch_duration_ms": analytics.avg_watch_duration_ms,
            "downloads": analytics.downloads or 0,
            "exports": analytics.exports or 0,
            "favorites": analytics.favorites or 0,
            "shares": analytics.shares or 0,
            "rejects": analytics.rejects or 0,
            "regenerations": analytics.regenerations or 0,
            "boundary_edits": analytics.boundary_edits or 0,
            "user_rating": analytics.user_rating,
            "last_interaction": analytics.last_interaction.isoformat() if analytics.last_interaction else None,
        }
    return await _async_db_query(_fetch)


# ─── QA Dashboard ────────────────────────────────────────────

@app.get("/api/qa/clip/{clip_id}")
async def get_qa_clip_detail(clip_id: str, db: Session = Depends(get_db)):
    def _fetch():
        c = db.query(Clip).filter(Clip.id == clip_id).first()
        if not c:
            raise HTTPException(404, "Clip not found")
        job = db.query(Job).filter(Job.id == c.job_id).first()
        analytics = db.query(ClipAnalytics).filter(ClipAnalytics.clip_id == clip_id).first()
        transcript = job.transcript if job else None
        clip_words_in_range = []
        if transcript and transcript.get("words"):
            clip_words_in_range = [
                w for w in transcript["words"]
                if c.start_time - 3 <= w.get("start", 0) <= c.end_time + 3
            ]
        return {
            "clip": {
                "id": c.id, "job_id": c.job_id, "filename": c.filename,
                "title": c.title, "hook_caption": c.hook_caption,
                "virality_score": c.virality_score, "reason": c.reason,
                "category": c.category, "hashtags": c.hashtags,
                "start_time": c.start_time, "end_time": c.end_time, "duration": c.duration,
                "context_start": c.context_start, "hook_start": c.hook_start,
                "payoff_end": c.payoff_end,
                "judge_provider": c.judge_provider, "judge_model": c.judge_model,
                "judge_notes": c.judge_notes,
                "signal_scores": c.signal_scores,
                "psychology_scores": c.psychology_scores,
                "quality_filter_results": c.quality_filter_results,
                "status": c.status, "render_version": c.render_version,
            },
            "transcript_segment": {
                "words": clip_words_in_range,
                "text": " ".join(w.get("word", "") for w in clip_words_in_range) if clip_words_in_range else "",
            },
            "analytics": {
                "views": analytics.preview_views or 0 if analytics else 0,
                "avg_watch_ms": analytics.avg_watch_duration_ms if analytics else None,
                "downloads": analytics.downloads or 0 if analytics else 0,
                "favorites": analytics.favorites or 0 if analytics else 0,
                "rejects": analytics.rejects or 0 if analytics else 0,
                "regenerations": analytics.regenerations or 0 if analytics else 0,
                "user_rating": analytics.user_rating if analytics else None,
            } if analytics else None,
            "url": get_storage().get_url(c.storage_path) if c.storage_path else None,
            "thumbnail_url": get_storage().get_url(c.thumbnail_path) if c.thumbnail_path else None,
        }
    return await _async_db_query(_fetch)


@app.get("/api/qa/job/{job_id}/review")
async def get_qa_job_review(job_id: str, db: Session = Depends(get_db)):
    def _fetch():
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            raise HTTPException(404, "Job not found")
        clips = db.query(Clip).filter(
            Clip.job_id == job_id, Clip.status == "active"
        ).order_by(Clip.virality_score.desc()).all()
        clip_summaries = []
        for c in clips:
            analytics = db.query(ClipAnalytics).filter(ClipAnalytics.clip_id == c.id).first()
            clip_summaries.append({
                "id": c.id, "title": c.title, "hook_caption": c.hook_caption,
                "virality_score": c.virality_score,
                "category": c.category, "reason": c.reason,
                "duration": c.duration,
                "context_start": c.context_start, "hook_start": c.hook_start,
                "payoff_end": c.payoff_end,
                "judge_provider": c.judge_provider, "judge_model": c.judge_model,
                "judge_notes": c.judge_notes,
                "psychology_scores": c.psychology_scores,
                "quality_filter_results": c.quality_filter_results,
                "rejects": analytics.rejects if analytics else 0,
                "favorites": analytics.favorites if analytics else 0,
                "user_rating": analytics.user_rating if analytics else None,
                "url": get_storage().get_url(c.storage_path) if c.storage_path else None,
            })
        return {
            "job_id": job_id, "status": job.status, "stage": job.stage,
            "source": job.source, "video_duration": job.video_duration,
            "clips_count": len(clip_summaries), "clips": clip_summaries,
            "errors": job.errors, "stage_timings": job.stage_timings,
            "generator_provider": job.provider, "has_transcript": bool(job.transcript),
        }
    return await _async_db_query(_fetch)


@app.get("/api/qa/stats")
async def get_qa_stats(db: Session = Depends(get_db)):
    def _fetch():
        total_clips = db.query(Clip).filter(Clip.status == "active").count()
        total_analytics = db.query(ClipAnalytics).count()
        total_views = db.query(ClipAnalytics).with_entities(sa_func.sum(ClipAnalytics.preview_views)).scalar() or 0
        total_downloads = db.query(ClipAnalytics).with_entities(sa_func.sum(ClipAnalytics.downloads)).scalar() or 0
        total_favorites = db.query(ClipAnalytics).with_entities(sa_func.sum(ClipAnalytics.favorites)).scalar() or 0
        total_rejects = db.query(ClipAnalytics).with_entities(sa_func.sum(ClipAnalytics.rejects)).scalar() or 0
        total_regenerations = db.query(ClipAnalytics).with_entities(sa_func.sum(ClipAnalytics.regenerations)).scalar() or 0
        avg_score = db.query(Clip).with_entities(sa_func.avg(Clip.virality_score)).filter(Clip.status == "active").scalar() or 0
        return {
            "total_clips": total_clips, "clips_with_analytics": total_analytics,
            "total_views": total_views, "total_downloads": total_downloads,
            "total_favorites": total_favorites, "total_rejects": total_rejects,
            "total_regenerations": total_regenerations,
            "avg_virality_score": round(float(avg_score), 2),
        }
    return await _async_db_query(_fetch)


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()
    async with _ws_lock:
        if job_id not in active_connections:
            active_connections[job_id] = []
        active_connections[job_id].append(websocket)

    def _fetch_job():
        db = SessionLocal()
        try:
            return db.query(Job).filter(Job.id == job_id).first()
        finally:
            db.close()

    job = await _async_db_query(_fetch_job)
    if job:
        initial_msg = {
            "type": "progress",
            "message": job.message,
            "progress": job.progress,
            "stage": job.stage,
            "retry_count": job.retry_count,
            "stage_timings": job.stage_timings,
        }
        if job.status == "complete":
            initial_msg = {
                "type": "complete", "message": job.message,
                "clips": job.clips or [], "transcript": job.transcript,
            }
        elif job.status in ("error", "failed"):
            initial_msg = {"type": "error", "message": job.message, "stage": job.stage}
        try:
            await websocket.send_json(initial_msg)
        except Exception:
            pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_lock:
            if job_id in active_connections:
                try:
                    active_connections[job_id].remove(websocket)
                except ValueError:
                    pass
                if not active_connections[job_id]:
                    del active_connections[job_id]
