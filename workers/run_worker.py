"""Run RQ worker for all Only Clipper queues."""
import os
import sys
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rq import SimpleWorker
from workers.job_queue import get_redis_conn, get_job_queue, get_download_queue, get_transcribe_queue, get_analyze_queue, get_render_queue

queues = [get_job_queue(), get_download_queue(), get_transcribe_queue(), get_analyze_queue(), get_render_queue()]

if __name__ == "__main__":
    w = SimpleWorker(queues, connection=get_redis_conn())
    w.work(with_scheduler=True)
