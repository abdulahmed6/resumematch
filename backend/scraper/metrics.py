"""Prometheus metrics for the scraping/indexing pipeline.

The gateway and scraper-API HTTP surfaces get request-level metrics for free
via `prometheus-fastapi-instrumentator` (see gateway/main.py and
scraper/service.py). These are the pipeline-level metrics that only make
sense from inside the Celery tasks themselves: how often scrapes succeed,
retry, fail permanently, and how deep the dead-letter queue is.
"""
from prometheus_client import Counter, Gauge

scrape_tasks_total = Counter(
    "resumematch_scrape_tasks_total",
    "Celery scrape/index task outcomes",
    ["task", "outcome"],  # outcome: success | retry | dlq
)

dlq_depth = Gauge(
    "resumematch_dlq_depth",
    "Current number of entries in the dead-letter queue",
)


def record_task_success(task_name: str) -> None:
    scrape_tasks_total.labels(task=task_name, outcome="success").inc()


def record_task_retry(task_name: str) -> None:
    scrape_tasks_total.labels(task=task_name, outcome="retry").inc()


def record_task_failure(task_name: str) -> None:
    """A task exhausted its retries and was routed to the DLQ."""
    scrape_tasks_total.labels(task=task_name, outcome="dlq").inc()
    try:
        from backend.scraper.dlq import dlq_length
        dlq_depth.set(dlq_length())
    except Exception:  # noqa: BLE001 - metrics must never break the task
        pass
