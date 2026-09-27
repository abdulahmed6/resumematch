"""Celery application for the distributed scraping pipeline.

In production (docker-compose) three worker containers consume from the
Redis broker in parallel. In dev/tests, `RM_CELERY_EAGER=true` runs tasks
synchronously in-process so no broker is required.
"""
from celery import Celery
from celery.schedules import crontab  # noqa: F401  (available for custom schedules)

from backend.common.config import get_settings

settings = get_settings()

celery_app = Celery(
    "resumematch",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["backend.scraper.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_always_eager=settings.celery_eager,
    task_eager_propagates=settings.celery_eager,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # fair dispatch across the 3 worker nodes
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "scheduled-scrape": {
            "task": "backend.scraper.tasks.scrape_source",
            "schedule": settings.scrape_interval_minutes * 60.0,
            "args": ("synthetic", settings.scrape_batch_size),
        },
    },
)
