"""
SQLAlchemy ORM models — PostgreSQL schema for ClipAura persistent media platform.
"""
import uuid
import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, JSON, ForeignKey, Boolean, event,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_new_id)
    email = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="queued")
    progress = Column(Integer, default=0)
    message = Column(String, default="Initializing...")
    stage = Column(String, default="queued")

    stage_started_at = Column(DateTime, nullable=True)
    stage_completed_at = Column(DateTime, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    temp_paths = Column(JSON, nullable=True)
    checkpoint_data = Column(JSON, nullable=True)

    video_path = Column(String, nullable=True)
    source = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    preset = Column(String, nullable=True)
    caption_style = Column(String, nullable=True)

    download_quality = Column(String, default="proxy")

    video_duration = Column(Float, nullable=True)
    video_resolution = Column(String, nullable=True)
    source_hash = Column(String, nullable=True)

    transcript = Column(JSON, nullable=True)
    clip_candidates = Column(JSON, nullable=True)
    clips = Column(JSON, nullable=True)
    errors = Column(JSON, nullable=True)
    stage_timings = Column(JSON, nullable=True)

    archived_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC), onupdate=lambda: datetime.datetime.now(datetime.UTC))

    # Relationship to clips
    rendered_clips = relationship("Clip", back_populates="job", cascade="all, delete-orphan")

    user = relationship("User", foreign_keys=[user_id])


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String, primary_key=True, default=_new_id)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    filename = Column(String, nullable=False)
    title = Column(String, nullable=True)
    hook_caption = Column(String, nullable=True)
    virality_score = Column(Float, default=0.0)
    reason = Column(String, nullable=True)
    category = Column(String, nullable=True)
    hashtags = Column(JSON, nullable=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    storage_path = Column(String, nullable=True)
    thumbnail_path = Column(String, nullable=True)
    subtitle_path = Column(String, nullable=True)
    content_hash = Column(String, nullable=True)
    render_version = Column(Integer, default=0)
    status = Column(String, default="active")
    words = Column(JSON, nullable=True)
    context_start = Column(Float, nullable=True)
    hook_start = Column(Float, nullable=True)
    payoff_end = Column(Float, nullable=True)
    judge_provider = Column(String, nullable=True)
    judge_model = Column(String, nullable=True)
    judge_notes = Column(JSON, nullable=True)
    signal_scores = Column(JSON, nullable=True)
    psychology_scores = Column(JSON, nullable=True)
    quality_filter_results = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC), onupdate=lambda: datetime.datetime.now(datetime.UTC))

    job = relationship("Job", back_populates="rendered_clips")
    analytics = relationship("ClipAnalytics", back_populates="clip", uselist=False, cascade="all, delete-orphan")


class ClipAnalytics(Base):
    """Behavioral feedback: watch time, downloads, exports, favorites, rejects, boundary edits."""
    __tablename__ = "clip_analytics"

    id = Column(String, primary_key=True, default=_new_id)
    clip_id = Column(String, ForeignKey("clips.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    # Engagement metrics
    preview_views = Column(Integer, default=0)
    preview_total_watch_ms = Column(Integer, default=0)
    downloads = Column(Integer, default=0)
    exports = Column(Integer, default=0)
    favorites = Column(Integer, default=0)
    shares = Column(Integer, default=0)

    # Feedback signals
    rejects = Column(Integer, default=0)
    regenerations = Column(Integer, default=0)
    boundary_edits = Column(Integer, default=0)

    # Quality signals
    user_rating = Column(Float, nullable=True)
    watch_completion_rate = Column(Float, nullable=True)
    avg_watch_duration_ms = Column(Integer, nullable=True)

    # Metadata
    last_interaction = Column(DateTime, nullable=True)
    interaction_history = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC), onupdate=lambda: datetime.datetime.now(datetime.UTC))

    clip = relationship("Clip", back_populates="analytics")
