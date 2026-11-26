# Load test methodology and results

This documents a real run of `backend/scripts/load_test.py`, not a projection
or an assumed number. Re-run the script yourself with `python -m
backend.scripts.load_test` to reproduce or update these figures — the script
prints a fresh, honest measurement every time, it does not hard-code output.

## What the script actually does

1. Seeds a fresh, throwaway SQLite database + FAISS index with the
   requested number of synthetic job postings (`--jobs`, default 5,200), using the **real** `scrape_source` → `index_jobs`
   Celery pipeline (not a shortcut / mock).
2. Launches the actual FastAPI gateway (`backend.gateway.main:app`) as a
   subprocess via `uvicorn`, against that seeded data.
3. Fires concurrent requests at `POST /api/search` using `httpx.AsyncClient`
   and measures, per request: end-to-end client latency (including any time
   spent waiting for a free concurrency slot) and the server's own
   self-reported search latency (the same number the gateway returns in its
   `/api/search` response and rolls up into `/api/stats`).

## Environment this was run in

Single sandboxed Linux container, 4 vCPUs, no Docker, no Postgres, no Redis,
no real network hop to a separate embedding microservice. Concretely:

- SQLite (not the docker-compose stack's Postgres)
- Celery in eager/in-process mode (not real Celery workers + Redis broker)
- The in-process "hashing" embedder (not `sentence-transformers`, which
  wasn't installed — see `requirements.txt` comment on that optional
  dependency)
- One or four `uvicorn` worker **processes** on one machine (not the 3
  separate worker nodes described in the scraping pipeline — that's a
  different axis of parallelism, for scraping, not for serving search
  requests)

This measures the FAISS search path and FastAPI request handling in
isolation. It is not a substitute for running the same script against the
full docker-compose (or Kubernetes) deployment, which this sandbox cannot
run. Numbers will differ there — plausibly better, given real worker
parallelism and a WAL-mode Postgres instead of a single SQLite file, but
that has not been measured and should not be assumed.

## Results

### 20,000 postings (current corpus size)

Seed: 19,995 synthetic postings (15 batches of 1,333), indexed through the
real pipeline in ~31 seconds.

**Unloaded search latency.** 500 sequential `POST /api/search` requests
(`top_k=10`, 5 rotating multi-skill queries) after 20 warm-up requests,
one uvicorn worker, no other load on the machine:

| Measure | p50 | p95 |
|---|---|---|
| Server-side search latency | **1.44 ms** | 1.97 ms |
| Client round trip (localhost) | 2.53 ms | |

**Under load.** `python -m backend.scripts.load_test --jobs 20000
--requests 2000 --concurrency 50`, load generator on the same 4 vCPUs:

| Workers | Requests | Errors | Wall time | Throughput | Server-side latency (mean / p50 / p95 / p99) |
|---|---|---|---|---|---|
| 1 | 2,000 | 0 | 7.6s | **261.8 req/s** | 88.3 / 59.8 / 252.9 / 356.3 ms |
| 4 | 2,000 | 0 | 6.6s | **301.6 req/s** | 14.5 / 5.1 / 49.9 / 224.8 ms |

### 5,190 postings (original run)

| Workers | Requests | Concurrency | Wall time | Throughput | Server-side latency (mean / p50 / p95 / p99) |
|---|---|---|---|---|---|
| 1 | 2,000 | 50 | 11.2s | 178.6 req/s | 5.3 / 1.7 / 34.9 / 74.6 ms |
| 4 | 2,000 | 50 | 8.5s | 236.6 req/s | 2.9 / 1.7 / 3.4 / 51.0 ms |

## How to read these numbers

- **Search itself is fast.** A flat FAISS inner-product lookup over ~20k
  384-dim vectors, plus the SQLite row fetch, takes about 1.4 ms at the
  median when the machine is otherwise idle.
- **Latency under load is mostly queueing.** With 50 concurrent clients on
  4 vCPUs that also run the load generator, requests wait for CPU. With one
  worker, the GIL serialises them, which is why its p50 is 60 ms. Four worker
  processes bring the p50 back to about 5 ms.
- **Throughput scales sub-linearly** (262 → 302 req/s going from 1 to 4
  workers). The likely causes are the load generator competing for the
  same CPUs and SQLite file-level locking. Neither has been profiled further.
- **This only measures the search path.** The scrape/index pipeline seeded
  ~640 postings/s in one process (19,995 in ~31 s, Celery eager mode). The
  distributed Celery worker pool (docker-compose or Kubernetes) has not been
  load-tested, so there is no measured per-node scrape throughput yet.
- **Embedder:** these runs use the in-process hashing embedder. A
  `sentence-transformers` backend adds model inference to every query and
  needs its own measurement.
