"""
Main FastAPI Application — Reconstructed Core Clipper Engine.
Exposes REST endpoints, static file hosting for previewing clips,
and in-memory WebSockets for live status & execution log streaming.
"""
import os
from dotenv import load_dotenv

# Load local .env environment variables
load_dotenv()

import re
import uuid
import shutil
import logging
import asyncio
import urllib.parse
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, UploadFile, File, Form, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session

import yt_dlp
from api.database import SessionLocal, init_db, Job
from workers.task_processor import (
    queue_video_job,
    subscribe_to_progress,
    dispatch_progress,
    STAGE_COMPLETE,
    STAGE_ERROR
)
from services.ffmpeg import PRESETS, CAPTION_STYLES, DEFAULT_CAPTION_STYLE, create_clip, safe_create_clip

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Initialize SQLite database schema
init_db()

app = FastAPI(title="Only Clipper API", version="1.0.0")

# Setup CORS for Next.js frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Open for easy local development integration
    allow_credentials=False, # Must be False when allow_origins is '*' to avoid browser CORS policy violations
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure folders exist
os.makedirs("storage", exist_ok=True)
os.makedirs("temp", exist_ok=True)

# Clean orphaned temp directories on startup (crashed worker jobs)
def cleanup_orphaned_dirs():
    """Remove temp/storage subdirectories that have no corresponding database job."""
    db = SessionLocal()
    try:
        active_job_ids = {row[0] for row in db.query(Job.id).all()}
        
        # Clean temp directories
        temp_root = os.getenv("TEMP_DIR", "./temp")
        if os.path.isdir(temp_root):
            for entry in os.listdir(temp_root):
                path = os.path.join(temp_root, entry)
                if os.path.isdir(path) and entry not in active_job_ids and entry != "work":
                    try:
                        shutil.rmtree(path, ignore_errors=True)
                        logger.info("Cleaned orphaned temp dir: %s", path)
                    except Exception as e:
                        logger.warning("Failed to clean temp dir %s: %s", path, e)
        
        # Clean storage directories (skip .gitkeep and db files)
        if os.path.isdir("storage"):
            for entry in os.listdir("storage"):
                path = os.path.join("storage", entry)
                if os.path.isdir(path) and entry not in active_job_ids:
                    try:
                        shutil.rmtree(path, ignore_errors=True)
                        logger.info("Cleaned orphaned storage dir: %s", path)
                    except Exception as e:
                        logger.warning("Failed to clean storage dir %s: %s", path, e)
    finally:
        db.close()

cleanup_orphaned_dirs()

# Mount storage folder so Next.js can stream videos and thumbnails directly
app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# Active WebSocket connections in memory: job_id -> list of WebSockets
active_connections = {}


async def broadcast_to_job_websockets(job_id: str, data: dict):
    """Sends a JSON payload to all active websockets for a specific job"""
    sockets = active_connections.get(job_id, [])
    for ws in list(sockets):
        try:
            await ws.send_json(data)
        except Exception:
            try:
                sockets.remove(ws)
            except ValueError:
                pass


def ws_progress_dispatcher(job_id: str, data: dict):
    """Thread-safe callback registered with the task processor to dispatch logs/progress over asyncio loop"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(
                lambda: asyncio.create_task(broadcast_to_job_websockets(job_id, data))
            )
    except Exception as e:
        logger.debug("Failed to dispatch progress in WebSocket thread: %s", e)


# Register our WebSocket broadcast bridge with the task worker
subscribe_to_progress(ws_progress_dispatcher)


# DB Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class WordUpdate(BaseModel):
    word: str
    start: float
    end: float


class EditClipRequest(BaseModel):
    job_id: str
    filename: str
    title: str
    hook_caption: str
    words: List[WordUpdate]
    caption_style: Optional[str] = None
    preset: Optional[str] = None


def is_valid_url(url: str) -> bool:
    """Validate string looks like a video URL, avoiding loopback/private network SSRF vectors"""
    patterns = [
        r'https?://(www\.)?youtube\.com/watch',
        r'https?://youtu\.be/',
        r'https?://(www\.)?twitch\.tv/',
        r'https?://(www\.)?vimeo\.com/',
        r'https?://(www\.)?dailymotion\.com/',
        r'https?://.+\.(mp4|mkv|mov|avi|webm)',
    ]
    return any(re.match(p, url, re.IGNORECASE) for p in patterns)


def download_video_url(url: str, output_path: str, progress_cb) -> str:
    """Download video from URL using yt-dlp to output_path with resilient retries & fallbacks"""
    progress_cb("Fetching video information from URL...", 1)
    
    # Configure base yt-dlp options
    ydl_opts = {
        'merge_output_format': 'mp4',
        'outtmpl': output_path,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 60,            # High socket timeout to handle slow/throttled streams
        'retries': 15,                  # More retries for transient errors
        'fragment_retries': 15,          # High fragment retries
        'nokeepalive': True,             # Prevents idle keepalive channel closures by CDN
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        },
    }

    def progress_hook(d):
        if d['status'] == 'downloading':
            pct = d.get('_percent_str', '').strip()
            progress_cb(f"Downloading video: {pct}", 3)

    ydl_opts['progress_hooks'] = [progress_hook]

    # Resilient multi-pass download attempts
    attempts = [
        # Attempt 1: best quality split video + audio
        {'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'},
        # Attempt 2: fallback to single pre-merged/unified format (bypasses fragment issues)
        {'format': 'best[ext=mp4]/best'}
    ]

    last_error = None
    for idx, config in enumerate(attempts):
        current_opts = {**ydl_opts, **config}
        progress_cb(f"Downloading video (Attempt {idx+1}/{len(attempts)})...", 2)
        try:
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                ydl.download([url])
            # If successfully downloaded, exit loop
            break
        except Exception as e:
            logger.warning("Download attempt %d failed: %s", idx + 1, e)
            last_error = e
            if idx < len(attempts) - 1:
                # Wait briefly before fallback retry
                import time
                time.sleep(3)
    else:
        # If all attempts failed
        raise RuntimeError(f"URL download failed: {last_error}")

    if not os.path.exists(output_path):
        raise FileNotFoundError("Video download completed but target file was not created.")

    progress_cb("URL download complete!", 4)
    return output_path



@app.get("/api/presets")
async def get_presets():
    """Return available export presets and caption styles"""
    return JSONResponse({
        "presets": PRESETS,
        "caption_styles": {k: {"name": k.replace("_", " ").title()} for k in CAPTION_STYLES},
    })


@app.get("/api/jobs")
async def get_jobs(db: Session = Depends(get_db)):
    """List all processing and completed jobs in reverse-chronological order"""
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    # Format and serialize job models
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
            "clips": j.clips or [],
            "created_at": j.created_at.isoformat() if j.created_at else None
        })
    return result


@app.get("/api/status/{job_id}")
async def get_status(job_id: str, db: Session = Depends(get_db)):
    """Retrieves full status and clips details for polling UI fallbacks"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JSONResponse({
        'id': job.id,
        'status': job.status,
        'stage': job.stage,
        'progress': job.progress,
        'message': job.message,
        'source': job.source,
        'clips': job.clips or [],
        'transcript': job.transcript,
        'errors': job.errors or [],
    })


@app.delete("/api/job/{job_id}")
async def delete_job(job_id: str, db: Session = Depends(get_db)):
    """Deletes job record and clears all generated files on local storage"""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    db.delete(job)
    db.commit()

    # Clear directories
    storage_dir = os.path.join("./storage", job_id)
    if os.path.exists(storage_dir):
        shutil.rmtree(storage_dir, ignore_errors=True)

    temp_dir = os.path.join(os.getenv("TEMP_DIR", "./temp"), job_id)
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)

    return {"success": True}


@app.post("/api/upload")
async def upload_video(
    file: UploadFile = File(None),
    url: str = Form(None),
    provider: str = Form("groq"),
    preset: str = Form("tiktok"),
    caption_style: str = Form(DEFAULT_CAPTION_STYLE),
    db: Session = Depends(get_db)
):
    """Accepts local video file upload or remote URL, creating a background process job"""
    job_id = str(uuid.uuid4())[:8]
    storage_dir = os.path.join("./storage", job_id)
    os.makedirs(storage_dir, exist_ok=True)

    source_name = ""
    video_path = os.path.join(storage_dir, "source.mp4")

    # 1. URL Download Mode
    if url and url.strip():
        clean_url = url.strip()
        if not is_valid_url(clean_url):
            raise HTTPException(status_code=400, detail="Invalid video URL protocol or domain.")
        
        source_name = clean_url

        # Create downloader job in DB
        new_job = Job(
            id=job_id,
            status='queued',
            stage='downloading',
            provider=provider,
            preset=preset,
            caption_style=caption_style,
            message='Queuing link download...',
            source=source_name,
            video_path=video_path,
            clips=[],
            errors=[]
        )
        db.add(new_job)
        db.commit()

        # Download URL inside background task immediately to prevent UI hanging
        def background_downloader():
            cb = make_progress_cb(job_id)
            try:
                # Cache lookup: check if this URL was already successfully downloaded
                db_cache = SessionLocal()
                jobs = db_cache.query(Job).filter(
                    Job.source == clean_url,
                    Job.id != job_id
                ).order_by(Job.created_at.desc()).all()

                cached_path = None
                for job in jobs:
                    if job.video_path and os.path.exists(job.video_path):
                        cached_path = job.video_path
                        break
                db_cache.close()

                if cached_path:
                    cb("Cached download found! Instantly restoring source video...", 2)
                    shutil.copy2(cached_path, video_path)
                    cb("Source video successfully restored from cache!", 4)
                else:
                    download_video_url(clean_url, video_path, cb)
                
                # Download complete, transition status and start core pipeline
                db_sub = SessionLocal()
                j = db_sub.query(Job).filter(Job.id == job_id).first()
                if j:
                    j.status = 'queued'
                    j.stage = 'queued'
                    j.message = 'Download complete. Queuing clipping pipeline...'
                    j.progress = 5
                    db_sub.commit()
                db_sub.close()
                
                queue_video_job(job_id)
            except Exception as e:
                db_sub = SessionLocal()
                j = db_sub.query(Job).filter(Job.id == job_id).first()
                if j:
                    j.status = 'error'
                    j.message = f"Download failed: {e}"
                    j.progress = 0
                    db_sub.commit()
                db_sub.close()
                dispatch_progress(job_id, {'type': 'error', 'message': f"Download failed: {e}"})

        # Run downloader thread in background executor
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, background_downloader)

    # 2. File Upload Mode
    elif file:
        source_name = file.filename
        
        # Stream file upload chunk-by-chunk to handle large files efficiently
        try:
            with open(video_path, 'wb') as f:
                while chunk := await file.read(1024 * 1024):
                    f.write(chunk)
        except Exception as e:
            if os.path.exists(video_path):
                os.remove(video_path)
            raise HTTPException(status_code=500, detail=f"File save failure: {e}")

        # Create job in database
        new_job = Job(
            id=job_id,
            status='queued',
            stage='queued',
            video_path=video_path,
            provider=provider,
            preset=preset,
            caption_style=caption_style,
            message='Upload complete, queuing clipping pipeline...',
            source=source_name,
            clips=[],
            errors=[]
        )
        db.add(new_job)
        db.commit()

        # Queue clipping core pipeline
        queue_video_job(job_id)
        
    else:
        raise HTTPException(status_code=400, detail="Must provide either a file upload or a public video URL.")

    return JSONResponse({'job_id': job_id})


@app.post("/api/clip/edit")
async def edit_clip(req: EditClipRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Regenerates a specific clip's captions and burns new video filters asynchronously.
    Returns status immediately, processing the task in the background.
    """
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if job.status == "processing":
        raise HTTPException(status_code=409, detail="A video compile is currently in progress. Please wait.")

    # Find the clip index & verify
    clips = job.clips or []
    target_clip = None
    clip_idx = -1
    for idx, c in enumerate(clips):
        if c['filename'] == req.filename:
            target_clip = dict(c)
            clip_idx = idx
            break

    if not target_clip or clip_idx == -1:
        raise HTTPException(status_code=404, detail="Clip not found in project catalog.")

    # Re-package word objects
    words_list = [{'word': w.word, 'start': w.start, 'end': w.end} for w in req.words]

    # Asynchronous background clip regeneration
    def regenerate_clip_task():
        db_task = SessionLocal()
        temp_output_path = None
        try:
            job_task = db_task.query(Job).filter(Job.id == req.job_id).first()
            if not job_task:
                return

            # Setup stage log
            job_task.status = 'processing'
            job_task.stage = "clip_regenerating"
            job_task.message = f"Regenerating subtitles for: {req.title}..."
            db_task.commit()

            # Push WS progress
            dispatch_progress(req.job_id, {
                'type': 'progress',
                'message': job_task.message,
                'progress': 90
            })

            # Re-compile video clip
            video_path = job_task.video_path
            output_dir = os.path.join("./storage", req.job_id)
            output_path = os.path.join(output_dir, req.filename)
            temp_output_path = f"{output_path}.tmp-{uuid.uuid4().hex}.mp4"

            clip_info = {
                'start_time': target_clip['start_time'],
                'end_time': target_clip['end_time'],
                'title': req.title,
                'hook_caption': req.hook_caption
            }

            style = req.caption_style or job_task.caption_style
            preset_choice = req.preset or job_task.preset

            # Call safe create clip
            result = safe_create_clip(
                video_path=video_path,
                clip_info=clip_info,
                words=words_list,
                output_path=temp_output_path,
                clip_index=clip_idx,
                caption_style=style,
                preset=preset_choice
            )

            if not result.get("ok"):
                raise RuntimeError(result.get("error", "FFmpeg failed re-compiling clip."))

            # Atomically replace target clip
            if os.path.exists(temp_output_path):
                if os.path.exists(output_path):
                    os.remove(output_path)
                os.rename(temp_output_path, output_path)

            # Update database
            updated_clips = []
            for idx_c, c_item in enumerate(job_task.clips or []):
                if idx_c == clip_idx:
                    prev_ver = int(c_item.get('render_version') or 0)
                    updated_clips.append({
                        **c_item,
                        'title': req.title,
                        'hook_caption': req.hook_caption,
                        'words': words_list,
                        'render_version': prev_ver + 1
                    })
                else:
                    updated_clips.append(c_item)

            job_task.clips = updated_clips
            job_task.status = 'complete'
            job_task.stage = STAGE_COMPLETE
            job_task.message = "Clip captions edited and re-rendered successfully!"
            job_task.progress = 100
            db_task.commit()

            # Push WebSocket completed packet
            dispatch_progress(req.job_id, {
                'type': 'complete',
                'message': job_task.message,
                'clips': job_task.clips,
                'transcript': job_task.transcript
            })

        except Exception as e:
            logger.exception("Clip caption regeneration failed")
            if temp_output_path and os.path.exists(temp_output_path):
                try:
                    os.remove(temp_output_path)
                except OSError:
                    pass

            job_err = db_task.query(Job).filter(Job.id == req.job_id).first()
            if job_err:
                errors = list(job_err.errors or [])
                errors.append({
                    "stage": "edit_failed",
                    "message": str(e),
                })
                job_err.errors = errors
                job_err.status = 'error'
                job_err.stage = STAGE_ERROR
                job_err.message = f"Failed to re-render clip edits: {e}"
                db_task.commit()

            dispatch_progress(req.job_id, {
                'type': 'error',
                'message': f"Failed to edit captions: {e}"
            })
        finally:
            db_task.close()

    background_tasks.add_task(regenerate_clip_task)
    return {"status": "processing", "message": "Caption re-render scheduled."}


@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket connection that streams real-time logs and progress ticks directly from backend thread"""
    await websocket.accept()
    
    # Store WebSocket in active directory
    if job_id not in active_connections:
        active_connections[job_id] = []
    active_connections[job_id].append(websocket)

    # Immediately push current db snapshot to socket
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            initial_msg = {
                'type': 'progress',
                'message': job.message,
                'progress': job.progress,
                'stage': job.stage
            }
            if job.status == 'complete':
                initial_msg = {
                    'type': 'complete',
                    'message': job.message,
                    'clips': job.clips or [],
                    'transcript': job.transcript
                }
            elif job.status == 'error':
                initial_msg = {
                    'type': 'error',
                    'message': job.message
                }
            try:
                await websocket.send_json(initial_msg)
            except Exception:
                pass
    finally:
        db.close()

    try:
        # Keep connection open until disconnect
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if job_id in active_connections:
            try:
                active_connections[job_id].remove(websocket)
            except ValueError:
                pass
            if not active_connections[job_id]:
                del active_connections[job_id]


def make_progress_cb(job_id):
    """Local helper for background URL downloader to update DB in real-time"""
    def cb(message, progress=None):
        db = SessionLocal()
        try:
            j = db.query(Job).filter(Job.id == job_id).first()
            if j:
                j.message = message
                if progress is not None:
                    j.progress = progress
                db.commit()
                dispatch_progress(job_id, {
                    'type': 'progress',
                    'progress': j.progress,
                    'message': j.message,
                    'stage': j.stage
                })
        except Exception as e:
            logger.error("Download progress cb error: %s", e)
        finally:
            db.close()
    return cb
