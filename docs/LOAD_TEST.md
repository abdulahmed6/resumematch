# Load test methodology and results

This documents a real run of `backend/scripts/load_test.py`, not a projection
or an assumed number. Re-run the script yourself with `python -m
backend.scripts.load_test` to reproduce or update these figures — the script
prints a fresh, honest measurement every time, it does not hard-code output.

## What the script actually does

1. Seeds a fresh, throwaway SQLite database + FAISS index with 5,190
   synthetic job postings, using the **real** `scrape_source` → `index_jobs`
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

Seed: 5,190 synthetic postings (15 batches of ~346, matching the project's
"5,000+ job postings" scale), indexed through the real pipeline in ~14
seconds.

Query set: 10 realistic multi-skill search phrases (e.g. "senior machine
learning engineer pytorch distributed training"), round-robined across
requests, `top_k=10`.

| Run | Workers | Requests | Concurrency | Wall time | Throughput | Server-side latency (mean / p50 / p95 / p99) |
|---|---|---|---|---|---|---|
| 1 | 1 | 2,000 | 50 | 11.2s | **178.6 req/s** | 5.3 / 1.7 / 34.9 / 74.6 ms |
| 2 | 4 | 2,000 | 50 | 8.5s | **236.6 req/s** | 2.9 / 1.7 / 3.4 / 51.0 ms |

The gateway's own rolling-average metric (`/api/stats.avg_query_latency_ms`,
computed over the last 200 queries, same code path production uses) read
**~1.6–1.8ms** in both runs.

### What this does and doesn't confirm

The actual FAISS lookup against 5,190 indexed postings is consistently in
the low single-digit milliseconds (median ~1.7ms, mean under 6ms even with
tail latency included) — that's the number to trust for "how fast is a
single search once it's running," and it's faster than the 40ms figure this
project's write-up has referenced, because this in-process hashing embedder
and flat FAISS index over ~5k vectors is simpler than a networked
sentence-transformers call would be. It does not, by itself, validate a
40ms figure for a sentence-transformers-backed deployment — that would need
to be measured with `RM_EMBEDDER_BACKEND=sentence-transformers` and the
optional dependency installed, which hasn't been done here.

**Throughput (178–237 req/s)** is a measurement of this one-machine,
one-SQLite-file, no-load-balancer setup — not a claim about the deployed
3-node architecture's capacity, and not comparable to a scrape throughput
figure (jobs scraped per day) since search and scrape are different
workloads on different services. Multi-process scaling from 1→4 uvicorn
workers was sub-linear (178 → 237 req/s, not ~700), most likely SQLite
file-level contention across processes and/or the load generator's own
client-side overhead running on the same 4 vCPUs as the server — that
bottleneck has not been root-caused further, and would look different
against Postgres.

**Bottom line for resume-writing purposes:** the semantic-search latency
claim is real, measured, and currently faster than what's been claimed — use
`avg_query_latency_ms` (~1.6ms here) or re-run against a
sentence-transformers-backed index to get a number for that specific
configuration. Any throughput or "concurrent jobs" figure describing the
*scraping* side (as opposed to search) should come from actually running
the Celery worker pipeline under load, not from this script, which only
exercises `/api/search`.
