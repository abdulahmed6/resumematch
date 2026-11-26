"""Measure end-to-end throughput of the distributed ingestion pipeline.

Unlike ``load_test.py`` (which exercises the search API), this script drives
the *write* path with real Celery workers and a real Redis broker:

    scrape_source task  ->  dedup + skill extraction + Postgres insert
                        ->  index_jobs task  ->  embedding service (HTTP)
                        ->  FAISS index  ->  Job.embedded = True

It dispatches ``--tasks`` scrape tasks of ``--batch`` postings each, then
polls the database until every new posting is marked ``embedded``. The clock
starts just before the first task is queued and stops when the last posting
is indexed, so queueing, worker scheduling, the DB round trips and the HTTP
hop to the embedding service are all included.

Prerequisites (see docs/PIPELINE_BENCHMARK.md for the exact commands):
  * Redis and Postgres running, RM_REDIS_URL / RM_DATABASE_URL pointing at them
  * RM_CELERY_EAGER=false
  * the embedding service running, RM_EMBEDDING_URL pointing at it
  * N Celery worker processes started with
    ``celery -A backend.scraper.celery_app.celery_app worker --concurrency=1``

Usage:
    python -m backend.scripts.pipeline_benchmark --tasks 30 --batch 350 --workers 3
"""
from __future__ import annotations

import argparse
import random
import json
import time

from sqlalchemy import func

from backend.common.config import get_settings
from backend.common.database import SessionLocal, init_db
from backend.common.models import Job, ScrapeRun
from backend.scraper.celery_app import celery_app
from backend.scraper.tasks import scrape_source


def _counts(source: str) -> tuple[int, int, int]:
    with SessionLocal() as db:
        total = db.query(func.count(Job.id)).filter(Job.source == source).scalar() or 0
        embedded = (
            db.query(func.count(Job.id))
            .filter(Job.source == source, Job.embedded.is_(True))
            .scalar()
            or 0
        )
        failed = db.query(func.count(ScrapeRun.id)).filter(ScrapeRun.status == "failed").scalar() or 0
    return total, embedded, failed


def _runs_finished() -> int:
    with SessionLocal() as db:
        return (
            db.query(func.count(ScrapeRun.id))
            .filter(ScrapeRun.status.in_(("done", "failed")))
            .scalar()
            or 0
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", type=int, default=30, help="number of scrape_source tasks to dispatch")
    parser.add_argument("--batch", type=int, default=350, help="postings per task")
    parser.add_argument("--workers", type=int, required=True,
                        help="how many worker processes are running (used only for the per-worker figure)")
    parser.add_argument("--source", default="synthetic")
    parser.add_argument("--seed-base", type=int, default=None,
                        help="seed offset so repeated runs generate new postings (default: current time)")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()

    settings = get_settings()
    if celery_app.conf.task_always_eager:
        raise SystemExit("RM_CELERY_EAGER is true: this benchmark needs real workers (set RM_CELERY_EAGER=false).")
    if not settings.embedding_url:
        raise SystemExit("RM_EMBEDDING_URL is empty: workers would each keep a private FAISS index. "
                         "Start the embedding service and point RM_EMBEDDING_URL at it.")

    init_db()
    # Large random offset so repeated runs generate fresh postings instead of duplicates.
    seed_base = args.seed_base if args.seed_base is not None else random.randrange(1, 1 << 30) * 1000
    total_before, embedded_before, failed_before = _counts(args.source)
    runs_before = _runs_finished()

    started = time.perf_counter()
    for i in range(args.tasks):
        scrape_source.delay(args.source, args.batch, seed_base + i)
    dispatched_s = time.perf_counter() - started

    target_new = None
    last_report = 0.0
    while True:
        total, embedded, failed = _counts(args.source)
        new_total = total - total_before
        new_embedded = embedded - embedded_before
        runs_done = _runs_finished() - runs_before
        elapsed = time.perf_counter() - started
        if runs_done >= args.tasks and target_new is None:
            target_new = new_total
        if target_new is not None and new_embedded >= target_new:
            break
        if failed - failed_before > 0:
            raise SystemExit(f"{failed - failed_before} scrape run(s) failed; check the worker logs.")
        if elapsed > args.timeout:
            raise SystemExit(f"Timed out after {elapsed:.0f}s ({new_embedded} of {new_total} indexed).")
        if elapsed - last_report >= 2:
            print(f"  t={elapsed:5.1f}s  inserted={new_total:6d}  indexed={new_embedded:6d}")
            last_report = elapsed
        time.sleep(0.2)

    wall = time.perf_counter() - started
    per_s = target_new / wall if wall else 0.0
    result = {
        "tasks": args.tasks,
        "batch": args.batch,
        "workers": args.workers,
        "postings_indexed": target_new,
        "dispatch_seconds": round(dispatched_s, 3),
        "wall_seconds": round(wall, 3),
        "postings_per_s_total": round(per_s, 1),
        "postings_per_s_per_worker": round(per_s / args.workers, 1),
    }
    print("=" * 72)
    print("PIPELINE BENCHMARK RESULT (real measurement from this run)")
    print("=" * 72)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
