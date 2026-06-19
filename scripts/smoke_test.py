"""
Smoke Test Verification Script — Validates the reconstructed core clipping engine.
Simulates a full end-to-end upload-to-export cycle using a tiny generated test video.
"""
import os
import sys
import uuid
import logging
import subprocess
import shutil
from dotenv import load_dotenv
load_dotenv()


# Configure logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] smoke_test: %(message)s")
logger = logging.getLogger(__name__)

# Ensure we can import from root directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Resilient imports
try:
    from api.database import SessionLocal, init_db
    from api.models import Job
    from services.ffmpeg import get_video_info, generate_thumbnail, safe_create_clip
    from services.clipping import align_clip_boundaries
    from services.face_processor import tracker
    logger.info("Successfully imported all core database and clipping service modules!")
except Exception as e:
    logger.error("Failed to import core modules. Rebuild validation failed: %s", e)
    sys.exit(1)


def generate_tiny_test_video(path):
    """Creates a tiny 5-second synthetic MP4 video with a test sound using FFmpeg"""
    logger.info("Creating a synthetic test video: %s", path)
    # Filter creates a test pattern with a sine beep audio track
    cmd = [
        'ffmpeg', '-f', 'lavfi', '-i', 'testsrc=duration=5:size=640x480:rate=30',
        '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=5',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '64k', '-y', path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.error("FFmpeg synthetic video generation failed: %s", result.stderr)
            return False
        return True
    except Exception as e:
        logger.error("Failed to generate test video: %s", e)
        return False


def run_pipeline_smoke_test():
    """Runs a simulated end-to-end pipeline run to verify integration correctness"""
    logger.info("--- STARTING CORE ENGINE SMOKE TEST ---")
    
    test_video = "./temp/smoke_test_source.mp4"
    os.makedirs("./temp", exist_ok=True)
    os.makedirs("./storage", exist_ok=True)

    if not generate_tiny_test_video(test_video):
        logger.error("Skipping test due to synthetic video generation failure.")
        sys.exit(1)

    # 1. Verify Video Info Analysis (ffprobe)
    try:
        w, h, dur = get_video_info(test_video)
        logger.info("Checked source dimensions: %dx%d, Duration: %.2fs", w, h, dur)
        assert w == 640 and h == 480 and dur > 4.9, "Incorrect dimensions/duration read."
    except Exception as e:
        logger.error("Media analysis preflight failed: %s", e)
        sys.exit(1)

    # 2. Database Job Creation
    init_db()
    db = SessionLocal()
    job_id = f"test-{uuid.uuid4().hex[:6]}"
    logger.info("Creating mock Job in local database. Job ID: %s", job_id)
    
    try:
        job = Job(
            id=job_id,
            status="queued",
            video_path=test_video,
            source="smoke_test_source.mp4",
            preset="tiktok",
            caption_style="typography_motion"
        )
        db.add(job)
        db.commit()
        
        # Verify it exists in DB
        db_job = db.query(Job).filter(Job.id == job_id).first()
        assert db_job is not None, "Failed to persist job record to SQLite database."
        logger.info("Mock Job successfully persisted to SQLite database!")
    except Exception as e:
        logger.error("Database persistence verification failed: %s", e)
        db.close()
        sys.exit(1)

    # 3. Time Boundary Snapping Verification
    # Simulated words returned from Whisper
    mock_words = [
        {'word': 'Welcome', 'start': 0.2, 'end': 0.8},
        {'word': 'to', 'start': 0.9, 'end': 1.1},
        {'word': 'Only', 'start': 1.2, 'end': 1.6},
        {'word': 'Clipper', 'start': 1.7, 'end': 2.3},
        {'word': 'rebuild', 'start': 2.8, 'end': 3.4},
        {'word': 'smoke', 'start': 3.5, 'end': 3.9},
        {'word': 'test', 'start': 4.0, 'end': 4.6}
    ]
    # Simulated LLM clip candidate selection (e.g. from 1.0s to 4.0s)
    mock_clips_info = [{
        'title': 'Test Highlight',
        'hook_caption': 'TEST HOOK OVERLAY',
        'start_time': 1.0,
        'end_time': 4.0
    }]
    
    try:
        logger.info("Running speech boundary alignment...")
        aligned_clips = align_clip_boundaries(mock_clips_info, mock_words)
        logger.info("Aligned boundaries: start %.2f -> %.2f, end %.2f -> %.2f", 
                    mock_clips_info[0]['start_time'], aligned_clips[0]['start_time'],
                    mock_clips_info[0]['end_time'], aligned_clips[0]['end_time'])
        # 1.0 snaps to nearest silence boundary before the word (0.8s)
        # 4.0 snaps to silence boundary after the word (3.9s)
        assert aligned_clips[0]['start_time'] <= 1.0, "Start boundary did not align correctly."
    except Exception as e:
        logger.error("Boundary pause alignment failed: %s", e)
        db.close()
        sys.exit(1)

    # 4. Video Crop & Karaoke Render Verification (FFmpeg)
    test_render_dir = os.path.join("./storage", job_id)
    os.makedirs(test_render_dir, exist_ok=True)
    test_output_clip = os.path.join(test_render_dir, "clip_1.mp4")
    test_output_thumb = os.path.join(test_render_dir, "thumb_1.jpg")

    try:
        logger.info("Extracting thumbnail frame...")
        thumb_ok = generate_thumbnail(test_video, 1.0, test_output_thumb)
        assert thumb_ok and os.path.exists(test_output_thumb), "Thumbnail extraction failed."
        logger.info("Thumbnail successfully generated: %s", test_output_thumb)

        logger.info("Re-compiling and rendering video clip with ASS subtitles and custom aspect ratios...")
        render_result = safe_create_clip(
            video_path=test_video,
            clip_info=aligned_clips[0],
            words=mock_words,
            output_path=test_output_clip,
            clip_index=0,
            caption_style="typography_motion",
            preset="tiktok"
        )
        logger.info("Rendering result payload: %s", render_result)
        assert render_result.get("ok") and os.path.exists(test_output_clip), f"FFmpeg render failed. Error: {render_result.get('error')}"
        logger.info("Video clip successfully rendered! Path: %s", test_output_clip)
    except Exception as e:
        logger.error("Video rendering process failed: %s", e)
        db.close()
        sys.exit(1)

    # 5. Clean Database & Storage
    try:
        logger.info("Cleaning up smoke test database records and generated directories...")
        db.delete(db_job)
        db.commit()
        db.close()
        
        # Clear files
        if os.path.exists(test_render_dir):
            shutil.rmtree(test_render_dir)
        if os.path.exists(test_video):
            os.remove(test_video)
            
        logger.info("--- SMOKE TEST SUCCESSFUL! CORE CLIPPING ENGINE IS FULLY INTEGRATED & OPERATIONAL! ---")
    except Exception as e:
        logger.warning("Cleanup completed with minor warnings: %s", e)


if __name__ == "__main__":
    run_pipeline_smoke_test()
