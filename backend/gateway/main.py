"""ResumeMatch API Gateway.

Public-facing FastAPI service. Responsibilities:
- semantic search over indexed jobs (via the embedding service),
- job browsing endpoints,
- resume upload + skill-gap analysis,
- pipeline stats,
- serving the built React SPA.
"""
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.common.config import get_settings
from backend.common.database import get_db, init_db
from backend.common.models import Job, ScrapeRun
from backend.common.schemas import (
    JobOut,
    SearchRequest,
    SearchResponse,
    SkillGapRequest,
    SkillGapResponse,
    StatsResponse,
)
from backend.common.skills import all_skills
from backend.embedding.client import get_embedding_client
from backend.gateway.skill_gap import analyze_skill_gap

# rolling window of recent query latencies for the stats endpoint
_LATENCIES: list[float] = []
_LATENCY_WINDOW = 200


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ResumeMatch Gateway", version="1.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)  # GET /metrics (Prometheus)


def _record_latency(ms: float) -> None:
    _LATENCIES.append(ms)
    if len(_LATENCIES) > _LATENCY_WINDOW:
        del _LATENCIES[: len(_LATENCIES) - _LATENCY_WINDOW]


def _search_jobs(db: Session, query: str, top_k: int,
                 remote_only: bool = False, seniority: str | None = None) -> tuple[list[JobOut], float, int]:
    """Semantic search + DB hydration + optional filters."""
    client = get_embedding_client()
    started = time.perf_counter()
    # over-fetch so post-filters still return enough results
    fetch_k = top_k * 3 if (remote_only or seniority) else top_k
    result = client.search(query, top_k=fetch_k)
    hits = result.get("hits", [])
    id_order = [h["id"] for h in hits]
    scores = {h["id"]: h["score"] for h in hits}

    jobs_by_id = {}
    if id_order:
        rows = db.query(Job).filter(Job.id.in_(id_order)).all()
        jobs_by_id = {j.id: j for j in rows}

    out: list[JobOut] = []
    for job_id in id_order:
        job = jobs_by_id.get(job_id)
        if job is None:
            continue
        if remote_only and not job.remote:
            continue
        if seniority and job.seniority != seniority:
            continue
        out.append(JobOut(**job.to_dict(), score=round(scores[job_id], 4)))
        if len(out) >= top_k:
            break

    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    _record_latency(latency_ms)
    return out, latency_ms, result.get("index_size", 0)


# --------------------------------------------------------------------------
# API routes
# --------------------------------------------------------------------------

@app.get("/api/healthz")
def healthz():
    return {"status": "ok", "service": "gateway"}


@app.post("/api/search", response_model=SearchResponse)
def search(req: SearchRequest, db: Session = Depends(get_db)):
    results, latency_ms, index_size = _search_jobs(
        db, req.query, req.top_k, req.remote_only, req.seniority
    )
    return SearchResponse(query=req.query, latency_ms=latency_ms,
                          total_indexed=index_size, results=results)


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    jobs = db.query(Job).order_by(Job.posted_at.desc()).offset(offset).limit(limit).all()
    return [JobOut(**j.to_dict()) for j in jobs]


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut(**job.to_dict())


@app.post("/api/skill-gap", response_model=SkillGapResponse)
def skill_gap(req: SkillGapRequest, db: Session = Depends(get_db)):
    if len(req.resume_text) > settings.max_resume_chars:
        raise HTTPException(status_code=413, detail="resume too large")
    query = req.query or req.resume_text[:1500]
    matched, _, _ = _search_jobs(db, query, req.top_k)
    job_ids = [j.id for j in matched]
    jobs = db.query(Job).filter(Job.id.in_(job_ids)).all() if job_ids else []
    # preserve ranking order
    jobs.sort(key=lambda j: job_ids.index(j.id))
    return SkillGapResponse(**analyze_skill_gap(req.resume_text, jobs))


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    """Accept a .txt/.md resume upload and return extracted text + skills."""
    if file.content_type not in ("text/plain", "text/markdown", "application/octet-stream", None):
        raise HTTPException(status_code=415, detail="only plain-text resumes are supported")
    raw = await file.read()
    if len(raw) > settings.max_resume_chars * 4:
        raise HTTPException(status_code=413, detail="file too large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="file must be UTF-8 text")
    from backend.common.skills import extract_skills

    return {"filename": file.filename, "chars": len(text),
            "text": text[: settings.max_resume_chars],
            "skills": extract_skills(text)}


@app.get("/api/skills")
def taxonomy():
    return {"skills": all_skills()}


@app.get("/api/stats", response_model=StatsResponse)
def stats(db: Session = Depends(get_db)):
    total = db.query(func.count(Job.id)).scalar() or 0
    sources = dict(
        db.query(Job.source, func.count(Job.id)).group_by(Job.source).all()
    )
    runs = db.query(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(5).all()
    try:
        indexed = get_embedding_client().index_size()
    except Exception:  # embedding service unreachable
        indexed = 0
    avg_latency = round(sum(_LATENCIES) / len(_LATENCIES), 3) if _LATENCIES else None
    return StatsResponse(
        total_jobs=total, total_indexed=indexed, sources=sources,
        last_runs=[r.to_dict() for r in runs], avg_query_latency_ms=avg_latency,
    )


# --------------------------------------------------------------------------
# Static SPA (built React app)
# --------------------------------------------------------------------------
_STATIC_DIR = os.environ.get(
    "RM_STATIC_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"),
)

if os.path.isdir(_STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    def spa_index():
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        base = os.path.abspath(_STATIC_DIR)
        candidate = os.path.abspath(os.path.join(base, path))
        if candidate.startswith(base + os.sep) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))
