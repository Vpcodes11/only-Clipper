"""
One-time migration: SQLite → PostgreSQL
Transfers all jobs and extracts clips from JSON blobs into the new clips table.
"""
import os
import sys
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

src_url = os.getenv("SQLITE_LEGACY_URL", "sqlite:///storage/clipper.db")
dst_url = os.getenv("DATABASE_URL", "postgresql://clipper:clipper@localhost:5432/clipper")

src_engine = create_engine(src_url)
dst_engine = create_engine(dst_url)

SrcSession = sessionmaker(bind=src_engine)
DstSession = sessionmaker(bind=dst_engine)

from api.models import Base, Job as PgJob, Clip as PgClip
Base.metadata.create_all(bind=dst_engine)

src = SrcSession()
dst = DstSession()

try:
    count = 0
    clip_count = 0

    for row in src.execute("SELECT * FROM jobs ORDER BY created_at"):
        jd = dict(row._mapping)
        clips_json = jd.get("clips")

        pg_job = PgJob(
            id=jd["id"],
            status=jd.get("status", "queued"),
            progress=jd.get("progress", 0),
            message=jd.get("message", ""),
            stage=jd.get("stage", "queued"),
            stage_started_at=jd.get("stage_started_at"),
            stage_completed_at=jd.get("stage_completed_at"),
            retry_count=jd.get("retry_count", 0),
            max_retries=jd.get("max_retries", 3),
            temp_paths=jd.get("temp_paths"),
            checkpoint_data=jd.get("checkpoint_data"),
            video_path=jd.get("video_path"),
            source=jd.get("source"),
            provider=jd.get("provider"),
            preset=jd.get("preset"),
            caption_style=jd.get("caption_style"),
            download_quality=jd.get("download_quality", "proxy"),
            video_duration=jd.get("video_duration"),
            video_resolution=jd.get("video_resolution"),
            source_hash=jd.get("source_hash"),
            transcript=jd.get("transcript"),
            clip_candidates=jd.get("clip_candidates"),
            clips=clips_json,
            errors=jd.get("errors"),
            stage_timings=jd.get("stage_timings"),
            created_at=jd.get("created_at"),
            updated_at=jd.get("updated_at"),
        )
        dst.add(pg_job)

        if clips_json and isinstance(clips_json, list):
            for idx, clip in enumerate(clips_json):
                clip_id = uuid.uuid4().hex[:12]
                pg_clip = PgClip(
                    id=clip_id,
                    job_id=jd["id"],
                    filename=clip.get("filename", f"clip_{idx+1}.mp4"),
                    title=clip.get("title", f"Clip {idx+1}"),
                    hook_caption=clip.get("hook_caption"),
                    virality_score=clip.get("virality_score", 0),
                    reason=clip.get("reason"),
                    category=clip.get("category"),
                    hashtags=clip.get("hashtags", []),
                    start_time=clip.get("start_time", 0),
                    end_time=clip.get("end_time", 0),
                    duration=clip.get("duration", 0),
                    status="active",
                    render_version=clip.get("render_version", 0),
                    words={"count": len(clip.get("words", []))},
                    created_at=pg_job.created_at,
                )
                dst.add(pg_clip)
                clip["clip_id"] = clip_id
                clip_count += 1

            pg_job.clips = clips_json

        count += 1
        if count % 10 == 0:
            dst.flush()
            print(f"Migrated {count} jobs, {clip_count} clips...")

    dst.commit()
    print(f"Done. Migrated {count} jobs with {clip_count} clips to PostgreSQL.")

finally:
    src.close()
    dst.close()
