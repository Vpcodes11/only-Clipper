"""
Task Processor — Shared progress broadcasting and logging infrastructure.
Old monolithic pipeline (process_video_job_impl) is deprecated in favor of
staged workers in pipeline_worker.py.

This file retains:
- dispatch_progress() — WebSocket broadcast bridge
- subscribe_to_progress() — callback registry
- make_progress_cb() — job-bound progress callback
"""
import os
import logging
from api.database import SessionLocal
from api.models import Job

logger = logging.getLogger(__name__)

# Core Stage Labels (legacy + new)
STAGE_PROCESSING = "processing"
STAGE_PREFLIGHTED = "preflighted"
STAGE_TRANSCRIBED = "transcribed"
STAGE_ANALYZED = "analyzed"
STAGE_ALIGNED = "aligned"
STAGE_RENDERING = "clips_rendering"
STAGE_RENDERED = "clips_rendered"
STAGE_COMPLETE = "complete"
STAGE_ERROR = "error"

# In-memory progress broadcasting registry (used by backend subscriber)
_progress_subscribers = []

import json
from workers.job_queue import get_redis_conn

def subscribe_to_progress(callback):
    """Register a callback to receive real-time progress broadcast updates"""
    _progress_subscribers.append(callback)

def start_redis_progress_listener():
    import threading
    def listener_thread():
        conn = None
        pubsub = None
        try:
            conn = get_redis_conn()
            pubsub = conn.pubsub()
            pubsub.subscribe("clipper:progress")
        except Exception as e:
            logger.warning("Redis unavailable for progress listener: %s. WebSocket updates will be sent direct.", e)
            return
        for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    job_id = data.pop("job_id", None)
                    if job_id:
                        for cb in _progress_subscribers:
                            try:
                                cb(job_id, data)
                            except Exception as e:
                                logger.debug("Failed to dispatch progress: %s", e)
                except Exception as e:
                    logger.error("Error processing pubsub message: %s", e)
    t = threading.Thread(target=listener_thread, daemon=True)
    t.start()

def dispatch_progress(job_id, data):
    """Pushes a progress packet via Redis PubSub so the backend can broadcast it to WebSockets.
    If Redis is unavailable, falls back to calling subscribers directly."""
    payload = dict(data)
    payload["job_id"] = job_id
    try:
        get_redis_conn().publish("clipper:progress", json.dumps(payload))
    except Exception as e:
        logger.debug("Failed to publish progress to redis: %s", e)
    # Also notify subscribers directly (works without Redis)
    for cb in _progress_subscribers:
        try:
            cb(job_id, dict(data))
        except Exception as cb_err:
            logger.debug("Failed to dispatch progress to subscriber: %s", cb_err)


def make_progress_cb(job_id):
    """Factory that returns a progress callback bound to a specific job_id.
    Commits status and progress directly to the SQLite database."""
    def progress_cb(message, progress=None):
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.message = message
                if progress is not None:
                    job.progress = progress
                db.commit()
                dispatch_progress(job_id, {
                    "type": "progress",
                    "progress": job.progress,
                    "message": job.message,
                    "stage": job.stage,
                })
        except Exception as e:
            logger.error("Failed to record progress for job %s: %s", job_id, e)
        finally:
            db.close()
    return progress_cb


def append_job_error(db, job, stage, message, clip_index=None, detail=None):
    """Append a structured error entry to the job database"""
    errors = list(job.errors or [])
    error = {"stage": stage, "message": str(message)[:500]}
    if clip_index is not None:
        error["clip_index"] = clip_index
    if detail:
        error["detail"] = str(detail)[-1000:]
    errors.append(error)
    job.errors = errors
    db.commit()
