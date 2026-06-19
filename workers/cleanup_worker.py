"""
Cleanup Worker — Scheduled maintenance for storage and database hygiene.
"""
import os
import time
import logging
from datetime import datetime, timedelta, timezone

from api.database import SessionLocal
from api.models import Clip, Job
from services.storage import get_storage

logger = logging.getLogger(__name__)

CLEANUP_AFTER_DAYS = 7
ORPHAN_STORAGE_DAYS = 1


def purge_deleted_clips():
    """Hard-delete clips with status='deleted' older than CLEANUP_AFTER_DAYS."""
    storage = get_storage()
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=CLEANUP_AFTER_DAYS)
        clips = db.query(Clip).filter(
            Clip.status == "deleted",
            Clip.updated_at < cutoff,
        ).all()

        for clip in clips:
            try:
                if clip.storage_path:
                    storage.delete(clip.storage_path)
                if clip.thumbnail_path:
                    storage.delete(clip.thumbnail_path)
            except Exception as e:
                logger.warning("Failed to delete storage for clip %s: %s", clip.id, e)
            db.delete(clip)

        db.commit()
        if clips:
            logger.info("Purged %d deleted clips", len(clips))
    finally:
        db.close()


def purge_orphaned_storage():
    """Delete storage objects that have no corresponding Clip row."""
    storage = get_storage()
    if not hasattr(storage, "list"):
        logger.debug("Storage backend does not support listing, skipping orphan purge")
        return

    db = SessionLocal()
    try:
        active_keys = set()
        clips = db.query(Clip).filter(Clip.status.in_(["active", "archived"])).all()
        for clip in clips:
            if clip.storage_path:
                active_keys.add(clip.storage_path)
            if clip.thumbnail_path:
                active_keys.add(clip.thumbnail_path)

        all_keys = storage.list("clips", max_keys=1000) or []
        for key in all_keys:
            if key not in active_keys:
                try:
                    storage.delete(key)
                    logger.info("Deleted orphaned storage key: %s", key)
                except Exception as e:
                    logger.warning("Failed to delete orphan %s: %s", key, e)
    finally:
        db.close()


def purge_orphaned_temp():
    """Clean up temp directories for jobs that no longer exist."""
    db = SessionLocal()
    try:
        active_job_ids = {row[0] for row in db.query(Job.id).all()}
        temp_root = os.getenv("TEMP_DIR", "./temp")
        if os.path.isdir(temp_root):
            for entry in os.listdir(temp_root):
                path = os.path.join(temp_root, entry)
                if os.path.isdir(path) and entry not in active_job_ids and entry != "work":
                    import shutil
                    try:
                        shutil.rmtree(path, ignore_errors=True)
                        logger.info("Cleaned orphaned temp dir: %s", path)
                    except Exception as e:
                        logger.warning("Failed to clean temp dir %s: %s", path, e)
    finally:
        db.close()


def run_all_cleanup():
    logger.info("Starting cleanup cycle")
    t0 = time.time()
    try:
        purge_deleted_clips()
    except Exception as e:
        logger.exception("purge_deleted_clips failed: %s", e)
    try:
        purge_orphaned_storage()
    except Exception as e:
        logger.exception("purge_orphaned_storage failed: %s", e)
    try:
        purge_orphaned_temp()
    except Exception as e:
        logger.exception("purge_orphaned_temp failed: %s", e)
    elapsed = (time.time() - t0) * 1000
    logger.info("Cleanup cycle complete in %.0f ms", elapsed)

