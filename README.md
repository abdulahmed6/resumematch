# ResumeMatch — Distributed Job-Matching Pipeline with Semantic Search

**Live demo: [resumematch-tr99.onrender.com](https://resumematch-tr99.onrender.com)**. It runs on Render's free plan, so if it has been idle, the first load takes about a minute while it wakes up. The demo is a single-service build (SQLite, in-process embedder, 5,190 synthetic postings). The full distributed stack runs locally with Docker Compose (below).

A full-stack job-matching platform. Job postings flow through a distributed scraping
pipeline (Celery workers over a Redis broker), get deduplicated and enriched with
extracted skills, then embedded into a FAISS vector index. A FastAPI gateway serves
semantic search, skill-gap analysis, and a React single-page app.

## Architecture

```
 sources ──► Celery workers ×3 ──► Postgres (jobs, scrape runs)
 (synthetic / (Redis broker,          │         │
  pluggable)   celery-beat)           ▼         └─► exhausted retries ─► DLQ
                              Embedding service      (Redis Streams)
                              (FastAPI, :8001)  ──► FAISS index
                                      ▲              (cosine / inner product)
                                      │ HTTP
 React SPA ◄────────────────── API Gateway (FastAPI, :8000)
                               search · skill-gap · stats · resume upload

 Scraper control-plane API (FastAPI, :8002) — trigger scrapes, inspect runs,
                                               inspect/replay/discard DLQ entries

 Prometheus (:9090) scrapes /metrics on all three services ──► Grafana (:3001)
```

Three FastAPI microservices (gateway, embedding, scraper control plane), 3 parallel
Celery worker replicas, Celery Beat for scheduled scrapes, Postgres and Redis, a
Redis-Streams dead-letter queue for tasks that exhaust their retries, and a
Prometheus + Grafana observability stack — all wired together with Docker Compose.
Kubernetes manifests (with HPA + KEDA autoscaling) are in `k8s/` for deploying the
same architecture to a cluster.

## Quick start (local dev, zero infrastructure)

Dev mode uses SQLite, an in-process embedder, and Celery eager mode — no Docker,
Postgres, or Redis needed.

```bash
pip install -r requirements.txt

# seed synthetic postings through the real pipeline + build the FAISS index
# (~10 s for 5,200 postings; use --count 20000 for the full demo corpus, ~30 s)
python -m backend.scripts.seed --count 5200

# build the frontend
cd frontend && npm install && npm run build && cd ..

# run the gateway (serves API + SPA)
uvicorn backend.gateway.main:app --port 8000
```

Open http://localhost:8000 — interactive API docs at http://localhost:8000/docs.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/abdulahmed6/resumematch)

One-click demo on Render's free tier (`render.yaml`: dev mode, SQLite, 5,200 synthetic postings). The first request after it has been idle takes about a minute while the service wakes up. This is how the [live demo](https://resumematch-tr99.onrender.com) is deployed.

## Production-style deployment

```bash
docker compose up --build --scale worker=3
```

Brings up Postgres, Redis, the embedding service, the gateway, the scraper API,
3 Celery worker nodes, Celery Beat, and a Prometheus + Grafana observability stack.
Seed via:

```bash
curl -X POST localhost:8002/scrape -H 'content-type: application/json' \
     -d '{"source": "synthetic", "count": 1000}'
```

### Kubernetes

`k8s/` has manifests for the same architecture on a cluster — Deployments/Services
for each stateless FastAPI service, a CPU-based HPA on the gateway, and a KEDA
ScaledObject that scales the worker pool on Celery queue depth. `k8s/monitoring/`
adds Prometheus (pod service discovery) and Grafana.

```bash
scripts/k8s-kind-up.sh          # local kind cluster with everything above
scripts/k8s-demo-autoscale.sh   # watch KEDA add workers and the HPA add gateways
```

See `k8s/README.md` for the layout and real-cluster setup. CI renders every
overlay and validates it with `kubeconform`.

## Reliability: dead-letter queue

Tasks that exhaust their Celery retries (`scrape_source`, `index_jobs`) are pushed to
a Redis-Streams-backed dead-letter queue (`backend/scraper/dlq.py`) — deliberately
separate from Celery's own broker queue — recording the task name, original args, and
failure reason. The scraper control-plane API exposes it:

| Endpoint | Method | Purpose |
|---|---|---|
| `/dlq` | GET | List DLQ entries |
| `/dlq/{entry_id}/replay` | POST | Re-dispatch the original task, then remove the entry |
| `/dlq/{entry_id}` | DELETE | Discard an entry without replaying it |

## Observability

All three FastAPI services (gateway, embedding, scraper-api) expose Prometheus
metrics on `GET /metrics` via `prometheus-fastapi-instrumentator` (request rate,
latency histograms, in-progress requests) plus custom pipeline metrics —
`resumematch_scrape_tasks_total{task,outcome}` and a `resumematch_dlq_depth` gauge
(`backend/scraper/metrics.py`). `docker compose up` also starts Prometheus (scrape
config in `docker/prometheus/prometheus.yml`) and Grafana (provisioned dashboard in
`docker/grafana/provisioning/dashboards/resumematch.json`) at http://localhost:3001
(admin/admin, or anonymous viewer access).

## Load testing

`backend/scripts/load_test.py` is a small asyncio + httpx harness that seeds a fresh
SQLite + FAISS pair, launches the gateway as a subprocess, and fires concurrent
requests at `/api/search`, reporting throughput and both client- and server-observed
latency percentiles:

```bash
python -m backend.scripts.load_test --jobs 20000 --requests 2000 --concurrency 50 --workers 4
```

Measured results (1.4 ms median search over 20,000 postings; ~300 req/s under
50-way concurrency on one 4-vCPU machine) and the limits of a single-machine
run compared with the full distributed stack are in `docs/LOAD_TEST.md`.

These are local benchmark numbers. The free-tier live demo runs on a fraction of a shared CPU, so its search latency is higher and varies (single-digit to a few hundred ms).

## Pipeline throughput

`backend/scripts/pipeline_benchmark.py` measures the ingestion path end to end
with real Celery workers, Redis, Postgres and the embedding service. On one
4-vCPU machine, 3 workers indexed **463–501 postings/s each** (about 1,400–1,500/s
total), steady as the index grew to 115k vectors. Setup, results and the two
bottlenecks the benchmark found are in `docs/PIPELINE_BENCHMARK.md`.

## Key API endpoints (gateway, :8000)

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/search` | POST | Semantic search (`{"query": "...", "top_k": 10, "remote_only": false}`) |
| `/api/jobs` | GET | Browse recent postings |
| `/api/jobs/{id}` | GET | Posting detail |
| `/api/skill-gap` | POST | Resume vs. matched jobs: coverage, missing skills |
| `/api/resume/upload` | POST | Upload a `.txt` resume, get extracted skills |
| `/api/stats` | GET | Corpus size, index size, per-source counts, query latency |
| `/api/skills` | GET | Skill taxonomy |

## Data sources

| Source | What it is | Use it for |
|---|---|---|
| `synthetic` | `SyntheticSource`: seeded generator of realistic postings | Demos, tests and benchmarks with no network |
| `greenhouse` | Greenhouse public job-board API (`boards-api.greenhouse.io`) | Real postings from companies listed in `RM_GREENHOUSE_BOARDS` |
| `lever` | Lever public postings API (`api.lever.co`) | Real postings from companies listed in `RM_LEVER_COMPANIES` |

Both job boards publish open roles as JSON for companies' own careers pages,
so no API key or HTML scraping is needed. All three sources implement
`fetch(count)` (`backend/scraper/sources.py`, `backend/scraper/job_boards.py`).
Dedup, skill extraction, embedding and indexing are the same for every source.
A board token that no longer exists is logged and skipped. If every board
fails, the task retries and then lands in the dead-letter queue.

```bash
# pull real postings (dev mode, no Docker needed)
python -m backend.scripts.seed --source greenhouse --count 500
# or through the running stack
curl -X POST localhost:8002/scrape -H 'content-type: application/json' -d '{"source": "lever", "count": 300}'
```

Set `RM_SCHEDULED_SOURCE=greenhouse` to have Celery Beat pull real postings on its schedule.

## Embeddings

Default backend is a fast hashing embedder (signed feature hashing of unigrams +
bigrams, 384-dim, L2-normalised) — runs anywhere with no model downloads. Switch to
true semantic embeddings with:

```bash
pip install sentence-transformers
RM_EMBEDDER_BACKEND=sentence-transformers uvicorn backend.embedding.service:app --port 8001
```

Both backends implement the same interface; FAISS indexing and search are unchanged.

## Configuration

All settings are environment variables prefixed `RM_` (see `.env.example`):
database URL, Redis URL, Celery eager mode, embedding backend/dimension, FAISS
index path, scrape batch size and schedule.

## Tests

```bash
pytest tests/ -v
```

Covers skill extraction, the embedder and FAISS index, the synthetic source, the
Celery pipeline (eager mode) including retry-exhaustion → DLQ, DLQ round-trip and
replay against fakeredis, skill-gap analysis, and every gateway / scraper-api /
embedding-service endpoint via FastAPI's TestClient (135 tests total).

## Project layout

```
backend/
  common/     config, database, models, schemas, skill taxonomy
  embedding/  embedder backends, FAISS index, embedding service + client
  scraper/    sources, Celery app, tasks, DLQ, metrics, control-plane API
  gateway/    public API, skill-gap analysis, SPA serving
  scripts/    seed, load_test
frontend/     React SPA (Vite)
docker/       backend Dockerfile, Prometheus config, Grafana provisioning
k8s/          Kubernetes manifests (Deployments, HPA, KEDA ScaledObject) + README
docs/         LOAD_TEST.md (methodology + real measured results)
tests/        pytest suite
```
