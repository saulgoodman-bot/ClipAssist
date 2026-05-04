from __future__ import annotations

from celery import Celery

celery_app = Celery("clipassist", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")
