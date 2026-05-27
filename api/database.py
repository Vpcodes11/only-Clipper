"""
SQLite database and SQLAlchemy ORM model setup.
Simplified auth-free model representing only video processing Jobs.
"""
import datetime
import os
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Database URL with storage folder fallback
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage/clipper.db")

# Ensure the parent storage folder exists
db_path = DATABASE_URL.replace("sqlite:///", "")
os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Required for SQLite multithreading
)

# Enable WAL mode for concurrent reads + writes without locking
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True)
    status = Column(String, default="queued")              # queued, processing, complete, error
    progress = Column(Integer, default=0)
    message = Column(String, default="Initializing...")
    stage = Column(String, default="queued")                # queued, preflighted, transcribed, analyzed, aligned, clips_rendering, clips_rendered, complete
    
    video_path = Column(String, nullable=True)
    source = Column(String, nullable=True)                  # Pasted URL or original filename
    provider = Column(String, nullable=True)                # groq, openai
    preset = Column(String, nullable=True)                  # tiktok, youtube_shorts, square, landscape
    caption_style = Column(String, nullable=True)           # typography_motion, hormozi, ali_abdaal, etc.

    transcript = Column(JSON, nullable=True)                # Full Whisper transcript details
    clip_candidates = Column(JSON, nullable=True)           # Candidates identified by LLM
    clips = Column(JSON, nullable=True)                     # Rendered clips metadata
    errors = Column(JSON, nullable=True)                     # Array of error stage & messages

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


def init_db():
    """Create all database tables if they do not exist"""
    Base.metadata.create_all(bind=engine)
