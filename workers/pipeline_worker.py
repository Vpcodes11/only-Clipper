"""
Pipeline Worker — Processes one pipeline stage per RQ job invocation.
Every stage is idempotent: re-running skips already-complete work.
On success: enqueues next stage. On failure: raises for RQ retry + backoff.
"""
import os
import time
import uuid
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

load_dotenv()

from api.database import SessionLocal
from api.models import Job, Clip
from workers.task_processor import dispatch_progress
from workers.job_queue import STAGES, enqueue_stage
from services.storage import get_storage

logger = logging.getLogger(__name__)


def process_stage(job_id: str, stage: str):
    """
    Process ONE pipeline stage. Called by RQ worker.
    Raises exception on failure → RQ retries with backoff → dead-letter after max retries.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Job %s not found for stage %s", job_id, stage)
            return

        t0 = time.time()
        job.stage = stage
        job.stage_started_at = datetime.now(timezone.utc)
        job.status = "processing"
        db.commit()

        dispatch_progress(job_id, {
            "type": "stage_start",
            "stage": stage,
            "progress": _stage_progress(stage),
            "message": f"Stage: {stage.replace('_', ' ').title()}..."
        })

        # === Stage Dispatch ===
        HANDLERS[stage](job, db)

        # Success: record timing, reset retries
        elapsed = (time.time() - t0) * 1000
        job.stage_completed_at = datetime.now(timezone.utc)
        job.retry_count = 0
        timings = job.stage_timings or {}
        timings[stage] = {
            "start": job.stage_started_at.isoformat(),
            "end": job.stage_completed_at.isoformat(),
            "duration_ms": round(elapsed, 1),
        }
        job.stage_timings = timings
        db.commit()

        dispatch_progress(job_id, {
            "type": "stage_complete",
            "stage": stage,
            "progress": _stage_progress(stage),
            "duration_ms": round(elapsed, 1),
        })

        # Enqueue next stage
        try:
            idx = STAGES.index(stage)
            if idx + 1 < len(STAGES):
                next_stage = STAGES[idx + 1]
                if next_stage != "failed":
                    enqueue_stage(job_id, next_stage)
                else:
                    _dispatch_complete(job)
            else:
                job.status = "complete"
                job.progress = 100
                db.commit()
                _dispatch_complete(job)
        except ValueError:
            logger.error("Stage %s not in STAGES list", stage)

    except Exception as e:
        logger.exception("Stage %s failed for job %s", stage, job_id)
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.retry_count = (job.retry_count or 0) + 1
                errors = list(job.errors or [])
                errors.append({
                    "stage": stage,
                    "message": str(e)[:500],
                    "retry": job.retry_count,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                job.errors = errors
                db.commit()

                dispatch_progress(job_id, {
                    "type": "stage_retry",
                    "stage": stage,
                    "retry": job.retry_count,
                    "max_retries": job.max_retries,
                    "error": str(e)[:300],
                })
        except Exception:
            logger.exception("Failed to record error for job %s", job_id)

        if job and job.retry_count >= job.max_retries:
            try:
                job.stage = "failed"
                job.status = "error"
                job.message = f"Failed at {stage}: {str(e)[:200]}"
                db.commit()
                dispatch_progress(job_id, {
                    "type": "error",
                    "stage": "failed",
                    "message": job.message,
                })
            except Exception:
                logger.exception("Failed to mark job %s as failed", job_id)

        raise
    finally:
        db.close()


# ─── Stage Handlers ──────────────────────────────────────────────


def _h_job_created(job, db):
    pass


def _h_metadata_fetched(job, db):
    from services.ffmpeg import get_video_info
    if not job.video_path or not os.path.exists(job.video_path):
        raise FileNotFoundError(f"Source video missing: {job.video_path}")

    if not (job.checkpoint_data or {}).get("source_storage_path"):
        storage = get_storage()
        source_key = f"sources/{job.id}/source.mp4"
        storage.upload(job.video_path, source_key, "video/mp4")
        job.checkpoint_data = (job.checkpoint_data or {}) | {"source_storage_path": source_key}
        db.commit()

    if job.video_duration:
        return

    src_w, src_h, duration = get_video_info(job.video_path)
    job.video_duration = float(duration)
    job.video_resolution = f"{src_w}x{src_h}"
    db.commit()


def _h_download_started(job, db):
    from services.downloader import download_video

    if job.video_path and os.path.exists(job.video_path):
        try:
            from services.ffmpeg import get_video_info
            get_video_info(job.video_path)
            return
        except Exception:
            logger.warning("Existing video corrupt, re-downloading job %s", job.id)

    if not job.source:
        raise ValueError("No source URL for download stage")

    storage_dir = os.path.join("./storage", job.id)
    os.makedirs(storage_dir, exist_ok=True)
    output_path = os.path.join(storage_dir, "source.mp4")

    quality = job.download_quality or "proxy"

    def progress_cb(msg, pct):
        dispatch_progress(job.id, {
            "type": "progress", "message": msg, "progress": pct, "stage": "download_started"
        })

    download_video(job.source, output_path, quality=quality, progress_cb=progress_cb)

    job.video_path = output_path
    db.commit()

    import hashlib
    sha = hashlib.sha256()
    with open(output_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    job.source_hash = sha.hexdigest()[:16]

    storage = get_storage()
    source_key = f"sources/{job.id}/source.mp4"
    storage.upload(output_path, source_key, "video/mp4")
    job.checkpoint_data = (job.checkpoint_data or {}) | {"source_storage_path": source_key}
    db.commit()


def _h_download_completed(job, db):
    if not job.video_path or not os.path.exists(job.video_path):
        raise FileNotFoundError("Download output missing")
    from services.ffmpeg import get_video_info
    get_video_info(job.video_path)


def _h_audio_extracted(job, db):
    from services.whisper import extract_audio, get_media_duration

    work_dir = os.path.join(os.getenv("TEMP_DIR", "./temp"), job.id, "work")
    os.makedirs(work_dir, exist_ok=True)
    audio_path = os.path.join(work_dir, "audio.mp3")

    if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
        job.temp_paths = (job.temp_paths or {}) | {"audio": audio_path}
        if not job.video_duration:
            job.video_duration = get_media_duration(job.video_path)
        db.commit()
        return

    extract_audio(job.video_path, audio_path)
    job.temp_paths = (job.temp_paths or {}) | {"audio": audio_path}
    if not job.video_duration:
        job.video_duration = get_media_duration(job.video_path)
    db.commit()


def _h_transcription_completed(job, db):
    from services.whisper import transcribe

    if job.transcript:
        return

    dispatch_progress(job.id, {
        "type": "progress", "message": "Transcribing audio via Whisper...", "progress": 20,
    })

    transcript = transcribe(
        job.video_path,
        progress_callback=lambda m, p: dispatch_progress(job.id, {
            "type": "progress", "message": m, "progress": p,
        }),
        provider=job.provider or "groq",
    )
    job.transcript = transcript
    db.commit()

    dispatch_progress(job.id, {
        "type": "transcript", "transcript": transcript,
    })


def _h_ai_analysis_completed(job, db):
    from services.clipping import analyze_transcript, align_clip_boundaries

    if job.clip_candidates:
        return

    if not job.transcript:
        raise RuntimeError("No transcript available for analysis")

    clips = analyze_transcript(
        job.transcript,
        progress_callback=lambda m, p: dispatch_progress(job.id, {
            "type": "progress", "message": m, "progress": p,
        }),
        provider=job.provider or "groq",
    )

    words = job.transcript.get("words", [])
    clips = align_clip_boundaries(clips, words)

    job.clip_candidates = clips
    db.commit()


def _h_clips_generated(job, db):
    if not job.clip_candidates:
        raise RuntimeError("No clip candidates generated")


def _h_render_started(job, db):
    """Render all clips in parallel. Persist to DB + object storage after each render."""
    from services.ffmpeg import safe_create_clip, generate_thumbnail

    clips_info = job.clip_candidates or []
    if not clips_info:
        raise RuntimeError("No clips to render")

    storage_dir = os.path.join("./storage", job.id)
    os.makedirs(storage_dir, exist_ok=True)

    storage = get_storage()

    existing = set()
    for i in range(len(clips_info)):
        if os.path.exists(os.path.join(storage_dir, f"clip_{i+1}.mp4")):
            existing.add(i)

    clip_results = []
    failures = []

    max_workers = min(4, os.cpu_count() or 2)

    # Generate thumbnails synchronously before the parallel render loop.
    # Thumbnails are fast (single frame) and this avoids wasting thread pool slots
    # on lightweight I/O tasks that compete with expensive FFmpeg renders.
    for idx, clip in enumerate(clips_info):
        if idx in existing:
            continue
        thumb_path = os.path.join(storage_dir, f"thumb_{idx+1}.jpg")
        try:
            generate_thumbnail(job.video_path, clip["start_time"], thumb_path)
        except Exception:
            logger.warning("Thumbnail generation failed for clip %d, continuing.", idx + 1)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for idx, clip in enumerate(clips_info):
            if idx in existing:
                continue
            output_path = os.path.join(storage_dir, f"clip_{idx+1}.mp4")
            fut = executor.submit(
                safe_create_clip,
                job.video_path, clip, job.transcript.get("words", []),
                output_path, idx, None,
                job.caption_style or "typography_motion",
                job.preset or "tiktok",
            )
            futures[fut] = (idx, clip, output_path)

        completed = 0
        total = max(len(futures), 1)
        for fut in as_completed(futures):
            idx, clip, output_path = futures[fut]
            completed += 1
            try:
                result = fut.result()
                if result.get("ok"):
                    clip_entry = _build_clip_entry(idx, clip, job.transcript)
                    _persist_clip(job.id, idx, clip_entry, storage_dir, storage, db)
                    clip_results.append(clip_entry)
                else:
                    failures.append((idx, result.get("error", "Unknown render failure")))
            except Exception as exc:
                failures.append((idx, str(exc)))

            pct = 80 + int((completed / total) * 18)
            dispatch_progress(job.id, {
                "type": "progress",
                "message": f"Rendered {completed}/{len(clips_info)} clips",
                "progress": pct,
            })

        for idx in existing:
            clip = clips_info[idx]
            clip_entry = _build_clip_entry(idx, clip, job.transcript)
            _persist_clip(job.id, idx, clip_entry, storage_dir, storage, db)
            clip_results.append(clip_entry)

    if failures:
        errors = list(job.errors or [])
        for idx, err in failures:
            errors.append({"stage": "render_started", "message": f"Clip {idx+1}: {err[:500]}"})
        job.errors = errors

    if not clip_results:
        raise RuntimeError(f"All {len(clips_info)} clips failed to render")

    clip_results.sort(key=lambda c: int(c["filename"].split("_")[1].split(".")[0]))
    job.clips = clip_results
    db.commit()

    dispatch_progress(job.id, {
        "type": "progress",
        "message": f"Rendered {len(clip_results)} clips ({len(failures)} failed)",
        "progress": 95,
    })


def _h_render_completed(job, db):
    """Verify renders exist on disk."""
    if not job.clips:
        raise RuntimeError("No clips recorded after render")
    storage_dir = os.path.join("./storage", job.id)
    for clip in job.clips:
        path = os.path.join(storage_dir, clip["filename"])
        if not os.path.exists(path):
            raise FileNotFoundError(f"Rendered clip missing: {path}")


def _h_export_completed(job, db):
    """Finalize job — upload remaining files to storage, cleanup temp, hydrate clip URLs."""
    import shutil
    storage = get_storage()
    if job.clips:
        for clip_entry in job.clips:
            clip_id = clip_entry.get("clip_id")
            if not clip_id:
                continue
            clip_row = db.query(Clip).filter(Clip.id == clip_id).first()
            if clip_row:
                clip_entry["url"] = storage.get_url(clip_row.storage_path)
                if clip_row.thumbnail_path:
                    clip_entry["thumbnail_url"] = storage.get_url(clip_row.thumbnail_path)
                clip_entry["clip_id"] = clip_row.id

    job.status = "complete"
    job.progress = 100
    job.message = "Pipeline complete!"
    db.commit()

    temp_dir = os.path.join(os.getenv("TEMP_DIR", "./temp"), job.id)
    if os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
            logger.info("Cleaned temp dir: %s", temp_dir)
        except Exception as e:
            logger.warning("Temp cleanup failed for %s: %s", temp_dir, e)


# ─── Clip Persistence ────────────────────────────────────────────


def _persist_clip(job_id: str, idx: int, clip_entry: dict, local_dir: str, storage, db):
    """Upload rendered clip + thumbnail to object storage and upsert the Clip row."""
    clip_row = db.query(Clip).filter(
        Clip.job_id == job_id,
        Clip.filename == clip_entry["filename"],
    ).first()
    clip_id = clip_row.id if clip_row else uuid.uuid4().hex[:12]
    clip_key = f"clips/{job_id}/{clip_id}.mp4"
    thumb_key = f"thumbnails/{job_id}/{clip_id}.jpg"

    local_clip = os.path.join(local_dir, clip_entry["filename"])
    local_thumb = os.path.join(local_dir, clip_entry.get("thumbnail", ""))

    clip_hash = None
    if os.path.exists(local_clip):
        clip_hash = storage.compute_hash(local_clip)
        storage.upload(local_clip, clip_key, "video/mp4")

    if os.path.exists(local_thumb):
        storage.upload(local_thumb, thumb_key, "image/jpeg")

    if not clip_row:
        clip_row = Clip(id=clip_id, job_id=job_id, filename=clip_entry["filename"])
        db.add(clip_row)

    clip_row.title = clip_entry.get("title")
    clip_row.hook_caption = clip_entry.get("hook_caption")
    clip_row.virality_score = clip_entry.get("virality_score", 0)
    clip_row.reason = clip_entry.get("reason")
    clip_row.category = clip_entry.get("category")
    clip_row.hashtags = clip_entry.get("hashtags", [])
    clip_row.start_time = clip_entry["start_time"]
    clip_row.end_time = clip_entry["end_time"]
    clip_row.duration = clip_entry["duration"]
    clip_row.context_start = clip_entry.get("context_start")
    clip_row.hook_start = clip_entry.get("hook_start")
    clip_row.payoff_end = clip_entry.get("payoff_end")
    clip_row.judge_provider = clip_entry.get("judge_provider")
    clip_row.judge_model = clip_entry.get("judge_model")
    clip_row.judge_notes = clip_entry.get("judge_notes")
    clip_row.signal_scores = clip_entry.get("signal_scores")
    clip_row.psychology_scores = clip_entry.get("psychology_scores")
    clip_row.quality_filter_results = clip_entry.get("quality_filter_results")
    clip_row.storage_path = clip_key
    clip_row.thumbnail_path = thumb_key if os.path.exists(local_thumb) else None
    clip_row.content_hash = clip_hash
    clip_row.status = "active"
    clip_row.words = clip_entry.get("words", [])
    clip_row.render_version = (clip_row.render_version or 0) + 1
    clip_row.updated_at = datetime.now(timezone.utc)
    db.flush()

    clip_entry["clip_id"] = clip_id
    clip_entry["storage_key"] = clip_key
    clip_entry["url"] = storage.get_url(clip_key)
    if clip_row.thumbnail_path:
        clip_entry["thumbnail_url"] = storage.get_url(clip_row.thumbnail_path)


# ─── Helpers ─────────────────────────────────────────────────────


HANDLERS = {
    "job_created": _h_job_created,
    "metadata_fetched": _h_metadata_fetched,
    "download_started": _h_download_started,
    "download_completed": _h_download_completed,
    "audio_extracted": _h_audio_extracted,
    "transcription_completed": _h_transcription_completed,
    "ai_analysis_completed": _h_ai_analysis_completed,
    "clips_generated": _h_clips_generated,
    "render_started": _h_render_started,
    "render_completed": _h_render_completed,
    "export_completed": _h_export_completed,
}


def _build_clip_entry(idx: int, clip: dict, transcript: dict) -> dict:
    words = transcript.get("words", []) if transcript else []
    return {
        "filename": f"clip_{idx+1}.mp4",
        "thumbnail": f"thumb_{idx+1}.jpg",
        "title": clip.get("title", f"Clip {idx+1}"),
        "hook_caption": clip.get("hook_caption", ""),
        "virality_score": clip.get("virality_score", 8.0),
        "reason": clip.get("reason", ""),
        "category": clip.get("category", "general"),
        "hashtags": clip.get("hashtags", []),
        "start_time": clip["start_time"],
        "end_time": clip["end_time"],
        "duration": round(clip["end_time"] - clip["start_time"], 1),
        "context_start": clip.get("context_start", clip.get("start_time", 0)),
        "hook_start": clip.get("hook_start", clip.get("start_time", 0)),
        "payoff_end": clip.get("payoff_end", clip.get("end_time", 0)),
        "judge_provider": clip.get("judge_provider"),
        "judge_model": clip.get("judge_model"),
        "judge_notes": clip.get("judge_notes"),
        "signal_scores": clip.get("signal_scores"),
        "psychology_scores": clip.get("psychology_scores"),
        "quality_filter_results": clip.get("quality_filter_results"),
        "words": [
            w for w in words
            if w["start"] >= clip["start_time"] - 0.3 and w["end"] <= clip["end_time"] + 0.3
        ],
    }


def _stage_progress(stage: str) -> int:
    return {
        "job_created": 0,
        "metadata_fetched": 5,
        "download_started": 10,
        "download_completed": 15,
        "audio_extracted": 20,
        "transcription_completed": 55,
        "ai_analysis_completed": 65,
        "clips_generated": 70,
        "render_started": 75,
        "render_completed": 95,
        "export_completed": 100,
    }.get(stage, 50)


def _dispatch_complete(job):
    dispatch_progress(job.id, {
        "type": "complete",
        "message": job.message or "Pipeline complete!",
        "clips": job.clips or [],
        "transcript": job.transcript,
    })
