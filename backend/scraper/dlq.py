"""Dead-letter queue for permanently-failed Celery tasks, backed by a Redis
Stream.

Celery/Redis handles the primary task queue (see celery_app.py) and already
gives us retries with backoff (`max_retries`) and crash recovery
(`task_acks_late` — an unacked task is redelivered if its worker dies
mid-execution). What Celery does *not* give us is a durable record of tasks
that exhausted their retries: by default a permanently-failed task just
raises and the failure result eventually expires from the result backend.

This module fills that gap with a small, dedicated use of Redis Streams
(`XADD` / `XRANGE` / `XDEL`) as an append-only, replayable log of failures —
independent of the Celery broker itself, so a failure here can never affect
the primary queue.

Entries are plain hashes of strings (Redis Streams fields are bytes/str),
so structured fields (args) are JSON-encoded.
"""
import json
import time
from functools import lru_cache
from typing import Any

import redis

from backend.common.config import get_settings

STREAM_KEY = "resumematch:dlq"

# Cap the stream so a pathological failure loop can't grow Redis memory
# unboundedly. ~ (roughly, Redis trims approximately with MAXLEN ~).
MAX_STREAM_LEN = 10_000


@lru_cache
def get_redis_client() -> "redis.Redis":
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def push_to_dlq(task_name: str, args: dict[str, Any], error: str, run_id: int | None = None) -> str:
    """Record a permanently-failed task. Returns the Redis Stream entry ID."""
    client = get_redis_client()
    fields = {
        "task": task_name,
        "args": json.dumps(args, default=str),
        "error": error[:2000],
        "run_id": "" if run_id is None else str(run_id),
        "failed_at": str(time.time()),
    }
    return client.xadd(STREAM_KEY, fields, maxlen=MAX_STREAM_LEN, approximate=True)


def dlq_length() -> int:
    client = get_redis_client()
    return client.xlen(STREAM_KEY)


def read_dlq(count: int = 50) -> list[dict[str, Any]]:
    """Return up to `count` DLQ entries, most recent first."""
    client = get_redis_client()
    # XREVRANGE walks the stream newest-first.
    entries = client.xrevrange(STREAM_KEY, count=count)
    out = []
    for entry_id, fields in entries:
        out.append({
            "id": entry_id,
            "task": fields.get("task"),
            "args": json.loads(fields.get("args", "{}")),
            "error": fields.get("error"),
            "run_id": int(fields["run_id"]) if fields.get("run_id") else None,
            "failed_at": float(fields["failed_at"]) if fields.get("failed_at") else None,
        })
    return out


def get_dlq_entry(entry_id: str) -> dict[str, Any] | None:
    client = get_redis_client()
    entries = client.xrange(STREAM_KEY, min=entry_id, max=entry_id)
    if not entries:
        return None
    _id, fields = entries[0]
    return {
        "id": _id,
        "task": fields.get("task"),
        "args": json.loads(fields.get("args", "{}")),
        "error": fields.get("error"),
        "run_id": int(fields["run_id"]) if fields.get("run_id") else None,
        "failed_at": float(fields["failed_at"]) if fields.get("failed_at") else None,
    }


def discard_dlq_entry(entry_id: str) -> bool:
    """Remove an entry from the stream (e.g. after a successful replay)."""
    client = get_redis_client()
    return client.xdel(STREAM_KEY, entry_id) > 0


def replay_dlq_entry(entry_id: str) -> dict[str, Any]:
    """Re-dispatch a failed task's original args through Celery, then remove
    it from the DLQ. Raises KeyError if the entry no longer exists."""
    import backend.scraper.tasks  # noqa: F401  local import: ensures tasks are
    # registered on celery_app.tasks before we look one up by name below, and
    # avoids an import cycle (tasks.py imports this module).
    from backend.scraper.celery_app import celery_app

    entry = get_dlq_entry(entry_id)
    if entry is None:
        raise KeyError(f"no DLQ entry with id {entry_id}")

    # NB: celery_app.send_task(...) is the wrong tool here — it's a low-level
    # broker-publish call that explicitly ignores `task_always_eager` and will
    # try to open a real broker connection even in dev/test. Looking the task
    # up in the registry and calling .apply_async() on it runs through the
    # normal Task machinery, which *does* respect task_always_eager (runs
    # inline, synchronously, in dev/test) while still publishing to the
    # broker normally in a real distributed deployment.
    task = celery_app.tasks[entry["task"]]
    result = task.apply_async(kwargs=entry["args"])
    discard_dlq_entry(entry_id)
    return {"replayed": True, "task": entry["task"], "new_task_id": result.id}
