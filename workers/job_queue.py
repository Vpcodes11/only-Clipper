"""
Queue Infrastructure — RQ/Redis-based job queue with retry, backoff, dead-letter.
Supports resumable staged pipeline execution.
"""
import os
import logging
from redis import Redis
from rq import Queue, Retry

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_redis_conn = None
_job_queue = None
_dlq = None
_download_queue = None
_transcribe_queue = None
_analyze_queue = None
_render_queue = None


def _get_redis():
    global _redis_conn
    if _redis_conn is None:
        _redis_conn = Redis.from_url(REDIS_URL)
    return _redis_conn


def get_redis_conn():
    return _get_redis()


def get_job_queue():
    global _job_queue
    if _job_queue is None:
        _job_queue = Queue("clipper-jobs", connection=_get_redis())
    return _job_queue


def get_dlq():
    global _dlq
    if _dlq is None:
        _dlq = Queue("clipper-dead-letter", connection=_get_redis())
    return _dlq


def get_download_queue():
    global _download_queue
    if _download_queue is None:
        _download_queue = Queue("clipper-download", connection=_get_redis())
    return _download_queue


def get_transcribe_queue():
    global _transcribe_queue
    if _transcribe_queue is None:
        _transcribe_queue = Queue("clipper-transcribe", connection=_get_redis())
    return _transcribe_queue


def get_analyze_queue():
    global _analyze_queue
    if _analyze_queue is None:
        _analyze_queue = Queue("clipper-analyze", connection=_get_redis())
    return _analyze_queue


def get_render_queue():
    global _render_queue
    if _render_queue is None:
        _render_queue = Queue("clipper-render", connection=_get_redis())
    return _render_queue


# Backwards-compatible module-level references (lazy, safe to import)
redis_conn = property(lambda self: _get_redis())
job_queue = property(lambda self: get_job_queue())
dlq = property(lambda self: get_dlq())
download_queue = property(lambda self: get_download_queue())
transcribe_queue = property(lambda self: get_transcribe_queue())
analyze_queue = property(lambda self: get_analyze_queue())
render_queue = property(lambda self: get_render_queue())

STAGES = [
    "job_created",
    "metadata_fetched",
    "download_started",
    "download_completed",
    "audio_extracted",
    "transcription_completed",
    "ai_analysis_completed",
    "clips_generated",
    "render_started",
    "render_completed",
    "export_completed",
    "failed",
]

STAGE_QUEUE_MAP = {
    "download_started": "download",
    "download_completed": "download",
    "audio_extracted": "transcribe",
    "transcription_completed": "transcribe",
    "ai_analysis_completed": "analyze",
    "clips_generated": "analyze",
    "render_started": "render",
    "render_completed": "render",
}


def _get_queue_for_stage(stage: str) -> Queue:
    """Route stage to appropriate queue for concurrency isolation"""
    queue_name = STAGE_QUEUE_MAP.get(stage)
    if queue_name == "download":
        return get_download_queue()
    elif queue_name == "transcribe":
        return get_transcribe_queue()
    elif queue_name == "analyze":
        return get_analyze_queue()
    elif queue_name == "render":
        return get_render_queue()
    return get_job_queue()


def enqueue_stage(job_id: str, stage: str):
    """
    Enqueue a single pipeline stage for a job.
    Retry with exponential backoff: 60s, 300s, 900s → dead-letter.
    """
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")

    queue = _get_queue_for_stage(stage)

    job = queue.enqueue(
        "workers.pipeline_worker.process_stage",
        args=(job_id, stage),
        job_timeout="30m",
        retry=Retry(max=3, interval=[60, 300, 900]),
        failure_ttl=86400 * 7,
        result_ttl=3600,
    )

    logger.info("Enqueued job_id=%s stage=%s queue=%s rq_job_id=%s", job_id, stage, queue.name, job.id)
    return job


def resume_job(job_id: str, from_stage: str = None):
    """
    Resume a job from its last completed stage (or specified stage).
    Called on app restart for stuck jobs, or via resume endpoint.
    """
    from api.database import SessionLocal
    from api.models import Job

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.error("Cannot resume: job %s not found", job_id)
            return None

        if from_stage:
            next_stage = from_stage
        elif job.stage == "failed":
            last_successful = _find_last_successful_stage(job)
            try:
                idx = STAGES.index(last_successful)
                next_stage = STAGES[idx + 1] if idx + 1 < len(STAGES) else STAGES[idx]
            except ValueError:
                next_stage = "job_created"
        else:
            next_stage = job.stage or "job_created"

        job.retry_count = 0
        job.status = "processing"
        db.commit()

        logger.info("Resuming job_id=%s from stage=%s", job_id, next_stage)
        return enqueue_stage(job_id, next_stage)
    finally:
        db.close()


def _find_last_successful_stage(job) -> str:
    """Walk the stage list backwards to find the last completed stage"""
    for stage in reversed(STAGES):
        if stage == "failed":
            continue
        if stage == "transcription_completed" and job.transcript:
            return stage
        if stage == "ai_analysis_completed" and job.clip_candidates:
            return stage
        if stage == "render_completed" and job.clips:
            return stage
        if stage == "download_completed" and job.video_path:
            return stage
    return "job_created"


def get_queue_stats() -> dict:
    """Return queue metrics for observability"""
    stats = {}
    for name, queue in [
        ("main", get_job_queue()),
        ("download", get_download_queue()),
        ("transcribe", get_transcribe_queue()),
        ("analyze", get_analyze_queue()),
        ("render", get_render_queue()),
    ]:
        stats[name] = {
            "count": queue.count,
            "started": len(queue.started_job_registry.get_job_ids()),
            "failed": queue.failed_job_registry.count,
            "scheduled": queue.scheduled_job_registry.count,
        }
    return stats
