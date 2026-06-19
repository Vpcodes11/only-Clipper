"""
Structured JSON logger for pipeline observability.
Emits stage_start, stage_complete, stage_error events with timing data.
"""
import json
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class JobLogger:
    """Per-job structured logger emitting JSON lines for ingestion into monitoring systems."""

    def __init__(self, job_id: str):
        self.job_id = job_id

    def _emit(self, event: str, **kwargs):
        record = {
            "job_id": self.job_id,
            "event": event,
            "timestamp": datetime.utcnow().isoformat(),
            **kwargs,
        }
        logger.info(json.dumps(record, default=str))

    def stage_start(self, stage: str, **kwargs):
        self._emit("stage_start", stage=stage, **kwargs)

    def stage_complete(self, stage: str, duration_ms: float, **kwargs):
        self._emit("stage_complete", stage=stage, duration_ms=round(duration_ms, 1), **kwargs)

    def stage_error(self, stage: str, error: str, retry: int = 0, **kwargs):
        self._emit("stage_error", stage=stage, error=str(error)[:500], retry_count=retry, **kwargs)

    def pipeline_start(self, **kwargs):
        self._emit("pipeline_start", **kwargs)

    def pipeline_complete(self, total_duration_ms: float, **kwargs):
        self._emit("pipeline_complete", total_duration_ms=round(total_duration_ms, 1), **kwargs)

    def download_cache(self, cache_type: str, **kwargs):
        self._emit("download_cache", cache_type=cache_type, **kwargs)
