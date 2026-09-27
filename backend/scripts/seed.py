"""Seed the database with 5,000+ synthetic job postings and build the FAISS index.

Usage:
    python -m backend.scripts.seed [--count 5200] [--batches 15]

The seed intentionally runs through the real Celery pipeline (`scrape_source`)
in batches, so it exercises the same code path production workers use.
"""
import argparse
import time

from backend.common.database import SessionLocal, init_db
from backend.common.models import Job
from backend.scraper.tasks import scrape_source


def seed(count: int = 5200, batches: int = 15) -> dict:
    init_db()
    per_batch = max(1, count // batches)
    started = time.perf_counter()
    total_new = 0
    for i in range(batches):
        res = scrape_source.delay("synthetic", per_batch, seed=1000 + i)
        payload = res.result if hasattr(res, "result") else res
        if isinstance(payload, dict):
            total_new += payload.get("new", 0)
        print(f"  batch {i + 1}/{batches}: {payload}")
    elapsed = time.perf_counter() - started
    with SessionLocal() as db:
        total = db.query(Job).count()
    summary = {"batches": batches, "new_jobs": total_new, "total_jobs": total,
               "elapsed_s": round(elapsed, 1)}
    print(f"Seed complete: {summary}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5200)
    parser.add_argument("--batches", type=int, default=15)
    args = parser.parse_args()
    seed(args.count, args.batches)
