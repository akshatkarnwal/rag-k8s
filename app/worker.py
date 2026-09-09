# worker.py
import os
from celery import Celery

# Inside Docker containers, use the service name ("redis") and internal port (6379).
# When running locally outside Docker, fall back to the host-mapped port (6380).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")

celery = Celery(
    "rag_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,   # lets AsyncResult report "STARTED", not just "PENDING"/"SUCCESS"
    result_expires=3600,       # job results auto-expire after 1hr, keeps Redis from filling up
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)

# Task modules get auto-discovered from here once tasks.py exists.
celery.autodiscover_tasks(["app"])