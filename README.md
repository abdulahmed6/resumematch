# ResumeMatch — Distributed Job-Matching Pipeline with Semantic Search

A full-stack job-matching platform. Job postings flow through a distributed scraping
pipeline (Celery workers over a Redis broker), get deduplicated and enriched with
extracted skills, then embedded into a FAISS vector index. A FastAPI gateway serves
semantic search, skill-gap analysis, and a React single-page app.

## Architecture

```
 sources ──► Celery workers ×3 ──► Postgres (jobs, scrape runs)
 (synthetic / (Redis broker,          │
  pluggable)   celery-beat)           ▼
                              Embedding service ──► FAISS index
                              (FastAPI, :8001)      (cosine / inner product)
                                      ▲
                                      │ HTTP
 React SPA ◄────────────────── API Gateway (FastAPI, :8000)
                               search · skill-gap · stats · resume upload

 Scraper control-plane API (FastAPI, :8002) — trigger scrapes, inspect runs
```

Three FastAPI microservices (gateway, embedding, scraper control plane), 3 parallel
Celery worker replicas, Celery Beat for scheduled scrapes, Postgres and Redis — all
wired together with Docker Compose.

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
3 Celery worker nodes, and Celery Beat. Seed via:

```bash
curl -X POST localhost:8002/scrape -H 'content-type: application/json' \
     -d '{"source": "synthetic", "count": 1000}'
```

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
Celery pipeline (eager mode), skill-gap analysis, and every gateway endpoint via
FastAPI's TestClient.

## Project layout

```
backend/
  common/     config, database, models, schemas, skill taxonomy
  embedding/  embedder backends, FAISS index, embedding service + client
  scraper/    sources, Celery app, tasks, control-plane API
  gateway/    public API, skill-gap analysis, SPA serving
  scripts/    seed
frontend/     React SPA (Vite)
docker/       shared backend Dockerfile
tests/        pytest suite
```
