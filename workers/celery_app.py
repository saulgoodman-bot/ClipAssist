from __future__ import annotations

from celery import Celery

from core.config import REDIS_URL

celery_app = Celery(
    "clipassist",
    broker=REDIS_URL,
    backend=REDIS_URL,
    # Without include, Celery never discovers the task module and
    # process_video_pipeline.delay() silently does nothing.
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Retry a failed task up to 3 times with exponential backoff
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)