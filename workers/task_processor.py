"""
Task Processor — Manages the background execution of the clipping pipeline.
Executes jobs in-process via ThreadPoolExecutor.
Eliminates Celery/Redis dependencies and provides robust log capturing,
progress broadcasting, and temporary file cleanup.
"""
import os
import shutil
import math
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from api.database import SessionLocal, Job
from services.whisper import transcribe
from services.clipping import analyze_transcript, align_clip_boundaries
from services.ffmpeg import get_video_info, generate_thumbnail, safe_create_clip

logger = logging.getLogger(__name__)

# Core Stage Labels
STAGE_PROCESSING = "processing"
STAGE_PREFLIGHTED = "preflighted"
STAGE_TRANSCRIBED = "transcribed"
STAGE_ANALYZED = "analyzed"
STAGE_ALIGNED = "aligned"
STAGE_RENDERING = "clips_rendering"
STAGE_RENDERED = "clips_rendered"
STAGE_COMPLETE = "complete"
STAGE_ERROR = "error"

# Global executor for video processing jobs
# Concurrency limit of 1 to ensure standard local system resources are not overwhelmed
job_executor = ThreadPoolExecutor(max_workers=1)

# In-memory progress broadcasting registry
_progress_subscribers = []


def subscribe_to_progress(callback):
    """Register a callback to receive real-time progress broadcast updates"""
    _progress_subscribers.append(callback)


def dispatch_progress(job_id, data):
    """Pushes a progress packet to all active WebSocket listeners"""
    for cb in _progress_subscribers:
        try:
            cb(job_id, data)
        except Exception as e:
            logger.debug("Failed to dispatch progress: %s", e)


def get_job(db, job_id):
    """Short-lived helper to fetch a Job"""
    return db.query(Job).filter(Job.id == job_id).first()


def make_progress_cb(job_id):
    """Factory that returns a progress callback bound to a specific job_id.
    Safely commits status and progress directly to the SQLite database."""
    def progress_cb(message, progress=None):
        db = SessionLocal()
        try:
            job = get_job(db, job_id)
            if job:
                job.message = message
                if progress is not None:
                    job.progress = progress
                db.commit()
                
                # Broadcast progress payload
                dispatch_progress(job_id, {
                    'type': 'progress',
                    'progress': job.progress,
                    'message': job.message,
                    'stage': job.stage
                })
        except Exception as e:
            logger.error("Failed to record progress for job %s: %s", job_id, e)
        finally:
            db.close()
    return progress_cb


def append_job_error(db, job, stage, message, clip_index=None, detail=None):
    """Append a structured error entry to the job database schema"""
    errors = list(job.errors or [])
    error = {
        "stage": stage,
        "message": str(message)[:500],
    }
    if clip_index is not None:
        error["clip_index"] = clip_index
    if detail:
        error["detail"] = str(detail)[-1000:]
    errors.append(error)
    job.errors = errors
    db.commit()


def process_video_job_impl(job_id):
    """Runs the full pipeline with checkpoint resilience & automatic cleanup"""
    db = SessionLocal()
    temp_dir = os.path.join(os.getenv("TEMP_DIR", "./temp"), job_id)
    
    try:
        job = get_job(db, job_id)
        if not job:
            logger.error("Job %s not found in database", job_id)
            return

        # Setup paths
        video_path = job.video_path
        preset = job.preset or 'tiktok'
        caption_style = job.caption_style or 'typography_motion'
        provider = job.provider or 'groq'

        progress_cb = make_progress_cb(job_id)
        progress_cb("Starting video clipping pipeline...", 2)

        # 1. Preflight Verification
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Source video file not found at: {video_path}")
            
        progress_cb("Analyzing source video properties...", 4)
        src_w, src_h, duration = get_video_info(video_path)
        
        job.stage = STAGE_PREFLIGHTED
        job.progress = 5
        db.commit()

        # 2. Transcription
        if job.transcript:
            logger.info("Found existing transcript. Skipping transcription.")
            transcript = job.transcript
        else:
            progress_cb("Extracting audio & performing Whisper transcription...", 10)
            transcript = transcribe(video_path, progress_callback=progress_cb, provider=provider)
            job.transcript = transcript
            job.stage = STAGE_TRANSCRIBED
            job.progress = 55
            db.commit()
            
            # Broadcast transcript immediately to the dashboard
            dispatch_progress(job_id, {
                'type': 'transcript',
                'transcript': transcript
            })

        # 3. AI Clip Analysis
        if job.clip_candidates:
            logger.info("Found existing clip candidates. Skipping analysis.")
            clips_info = job.clip_candidates
        else:
            progress_cb("Analyzing transcript for viral moments...", 58)
            clips_info = analyze_transcript(transcript, progress_callback=progress_cb, provider=provider)
            job.clip_candidates = clips_info
            job.stage = STAGE_ANALYZED
            job.progress = 70
            db.commit()

        # 4. Boundary Speech Snapping
        if job.stage == STAGE_ANALYZED:
            progress_cb("Snapping clip boundaries to natural speech pauses...", 72)
            clips_info = align_clip_boundaries(clips_info, transcript.get('words', []))
            job.clip_candidates = clips_info
            job.stage = STAGE_ALIGNED
            job.progress = 74
            db.commit()

        # 5. FFmpeg Video Rendering & Thumbnailing
        # Prepare output directory
        storage_dir = os.path.join("./storage", job_id)
        os.makedirs(storage_dir, exist_ok=True)
        
        job.stage = STAGE_RENDERING
        job.progress = 75
        job.message = "Rendering clips..."
        db.commit()

        # Create clip thumbnails
        progress_cb("Generating clip thumbnails...", 76)
        for idx, clip in enumerate(clips_info):
            thumb_path = os.path.join(storage_dir, f"thumb_{idx+1}.jpg")
            generate_thumbnail(video_path, clip['start_time'], thumb_path)

        # Render clips in parallel
        progress_cb("Compiling & rendering video clips...", 80)
        clip_results = []
        render_failures = []

        # Thread pool inside worker to render up to 2 clips concurrently (optimizes CPU threads)
        with ThreadPoolExecutor(max_workers=min(2, os.cpu_count() or 1)) as renderer:
            futures = {}
            for idx, clip in enumerate(clips_info):
                output_path = os.path.join(storage_dir, f"clip_{idx+1}.mp4")
                future = renderer.submit(
                    safe_create_clip,
                    video_path, clip, transcript.get('words', []),
                    output_path, idx, None, caption_style, preset
                )
                futures[future] = (idx, clip)

            completed = 0
            for future in as_completed(futures):
                idx, clip = futures[future]
                completed += 1
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}

                if result.get("ok"):
                    # Record successfully rendered clip details
                    clip_results.append({
                        'filename': f"clip_{idx+1}.mp4",
                        'thumbnail': f"thumb_{idx+1}.jpg",
                        'title': clip['title'],
                        'hook_caption': clip.get('hook_caption', ''),
                        'virality_score': clip.get('virality_score', 8.0),
                        'reason': clip.get('reason', ''),
                        'category': clip.get('category', 'general'),
                        'hashtags': clip.get('hashtags', []),
                        'start_time': clip['start_time'],
                        'end_time': clip['end_time'],
                        'duration': round(clip['end_time'] - clip['start_time'], 1),
                        'words': [
                            w for w in transcript.get('words', [])
                            if w['start'] >= clip['start_time'] - 0.3 and w['end'] <= clip['end_time'] + 0.3
                        ]
                    })
                    if result.get("attempt") == "static_fallback":
                        append_job_error(db, job, STAGE_RENDERING, f"Clip {idx+1} rendered with static center-crop fallback.")
                else:
                    render_failures.append((idx, clip, result.get("error")))
                    append_job_error(db, job, STAGE_RENDERING, f"Clip {idx+1} failed rendering.", clip_index=idx+1, detail=result.get("error"))

                pct = 80 + int((completed / max(len(clips_info), 1)) * 18)
                progress_cb(f"Rendered {completed} of {len(clips_info)} clips...", pct)

        # Enforce that at least one clip was successfully rendered
        if not clip_results:
            errors_str = "; ".join([f"Clip {idx+1}: {err}" for idx, _, err in render_failures])
            raise RuntimeError(f"All clip renders failed. Details: {errors_str}")

        # Update database with completed clips
        job.clips = clip_results
        job.stage = STAGE_COMPLETE
        job.status = "complete"
        job.progress = 100
        
        suffix = ""
        if render_failures:
            suffix = f" ({len(render_failures)} clip(s) failed and were skipped)."
        job.message = f"Done! {len(clip_results)} clips rendered successfully{suffix}."
        db.commit()

        # Broadcast completion
        dispatch_progress(job_id, {
            'type': 'complete',
            'message': job.message,
            'clips': clip_results,
            'transcript': job.transcript
        })

    except Exception as e:
        logger.exception("Pipeline failed for job %s", job_id)
        db.rollback()
        tb = traceback.format_exc()
        
        # Reload job in a fresh session to ensure rollback didn't detach it
        job = get_job(db, job_id)
        if job:
            append_job_error(db, job, job.stage or STAGE_PROCESSING, str(e), detail=tb)
            job.status = "error"
            job.message = str(e)
            job.progress = 0
            db.commit()
            
        # Broadcast error
        dispatch_progress(job_id, {
            'type': 'error',
            'message': str(e)
        })
        
    finally:
        db.close()
        
        # Resilient Temporary Directory Cleanup
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info("Cleaned up temporary working directory: %s", temp_dir)
            except Exception as e:
                logger.error("Failed to delete temp dir %s: %s", temp_dir, e)


def queue_video_job(job_id):
    """Queues a job to be processed by the background task executor"""
    job_executor.submit(process_video_job_impl, job_id)
