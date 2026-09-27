# ResumeMatch — Distributed Job-Matching Pipeline with Semantic Search

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

# seed 5,000+ synthetic postings through the real pipeline + build the FAISS index
python -m backend.scripts.seed --count 5200

# build the frontend
cd frontend && npm install && npm run build && cd ..

# run the gateway (serves API + SPA)
uvicorn backend.gateway.main:app --port 8000
```

Open http://localhost:8000 — interactive API docs at http://localhost:8000/docs.

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
ScaledObject that scales the worker pool on Celery queue depth. See `k8s/README.md`
for prerequisites (KEDA, metrics-server, a pushed container image) and an honest
caveat: these manifests are authored and YAML-validated but have not been applied to
a live cluster from this environment.

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
python -m backend.scripts.load_test --jobs 5200 --requests 2000 --concurrency 50
```

Real measured results (single machine, in-process hashing embedder, SQLite) and an
honest discussion of this setup's limitations vs. the full distributed stack are in
`docs/LOAD_TEST.md`.

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
