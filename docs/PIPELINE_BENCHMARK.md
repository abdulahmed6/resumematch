# Ingestion pipeline benchmark

This measures the **write path** with real infrastructure: Celery workers
consuming from a Redis broker, Postgres, and the embedding microservice over
HTTP. It complements `docs/LOAD_TEST.md`, which only measures the search API.

## What one posting goes through

1. `scrape_source` task (a Celery worker) fetches a batch from the source.
2. Dedup: one indexed lookup of the batch's `(source, external_id)` pairs.
3. Skill extraction (`backend/common/skills.py`), then Postgres insert.
4. `index_jobs` task is queued to Redis and picked up by any worker.
5. That worker sends the texts to the embedding service (`POST /index/add`),
   which embeds them and adds them to the FAISS index.
6. The worker marks the rows `embedded = true`.

`backend/scripts/pipeline_benchmark.py` dispatches N `scrape_source` tasks and
stops the clock when the last new posting is `embedded`. Everything from
queueing to indexing is inside the measured time.

## Results

Run on 2026-11-26 on one Linux container with 4 vCPUs. Postgres 16, Redis 7,
the embedding service and all workers shared that machine. Each worker is
one Celery process with `--concurrency=1`. Batches were 350 postings, and the
embedder was the hashing backend.

| Workers | Tasks per run | Postings per run | Wall time | Total postings/s | Per worker |
|---|---|---|---|---|---|
| 1 | 30 | 10,500 | 17.6–17.9 s | 588–597 | 588–597 |
| 3 | 60 | 19,950–21,000 | 14.0–14.4 s | 1,388–1,502 | **463–501** |

There were 3 runs with 1 worker and 4 runs with 3 workers, back to back on
the same database. The index grew from 0 to 115,500 vectors, and throughput
stayed flat. Runs that indexed fewer than 21,000 postings had duplicates
dropped by the dedup step.

Scaling from 1 to 3 workers is sub-linear: 2.5x the throughput with 3x the
workers. All 3 workers, Postgres and the embedding service compete for the
same 4 vCPUs, and every `index_jobs` call goes through one embedding service
process.

## Two bottlenecks this benchmark found (both fixed)

- **Index save on every batch.** The embedding service called
  `faiss.write_index` after every `/index/add`. That rewrites the whole file
  (about 1.5 KB per vector), so each batch got slower as the index grew. With
  3 workers, back-to-back runs fell from 1,075 to 709 postings/s while the
  index went from about 77k to 140k vectors. Saves are now throttled to at
  most once every `RM_INDEX_SAVE_INTERVAL_SECONDS` (default 5), plus on
  shutdown. Postgres is still the source of truth: `POST /index/rebuild`
  restores anything added after the last save if the service crashes.
- **Dedup loaded every ID.** `scrape_source` read every `external_id` for the
  source before each batch. It now looks up only the IDs in the batch, using
  the `uq_source_external` unique index.

## Reproduce it

```bash
# 1. Infrastructure (or `docker compose up -d postgres redis`)
docker run -d --name rm-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=resumematch -p 5432:5432 postgres:16-alpine
docker run -d --name rm-redis -p 6379:6379 redis:7-alpine

# 2. Environment for every terminal below
export RM_DATABASE_URL=postgresql+psycopg2://postgres:pw@localhost:5432/resumematch
export RM_REDIS_URL=redis://localhost:6379/0
export RM_CELERY_EAGER=false
export RM_EMBEDDING_URL=http://127.0.0.1:8001

# 3. Embedding service (owns the FAISS index, so no embedding URL for itself)
RM_EMBEDDING_URL= uvicorn backend.embedding.service:app --port 8001

# 4. Workers, one terminal each (or one with `&`)
celery -A backend.scraper.celery_app.celery_app worker --concurrency=1 -n w1@%h
celery -A backend.scraper.celery_app.celery_app worker --concurrency=1 -n w2@%h
celery -A backend.scraper.celery_app.celery_app worker --concurrency=1 -n w3@%h

# 5. Benchmark
python -m backend.scripts.pipeline_benchmark --tasks 60 --batch 350 --workers 3
```

Results depend on the CPU. On a laptop, run it a few times and use the range.
