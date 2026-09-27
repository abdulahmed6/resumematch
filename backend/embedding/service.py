"""Embedding microservice.

Owns the embedder and the FAISS index. Other services talk to it via HTTP:

    POST /embed          -> vectors for arbitrary texts
    POST /index/add      -> embed texts and upsert into the FAISS index
    POST /index/search   -> nearest-neighbour search for a query string
    POST /index/rebuild  -> re-embed every job in the database
    GET  /healthz        -> liveness + index size
"""
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from backend.common.config import get_settings
from backend.common.database import SessionLocal, init_db
from backend.common.models import Job
from backend.embedding.embedder import get_embedder
from backend.embedding.index import get_index


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=1000)


class IndexAddRequest(BaseModel):
    ids: list[int]
    texts: list[str]


class IndexSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=200)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_embedder()
    get_index()
    yield
    get_index().save()


app = FastAPI(title="ResumeMatch Embedding Service", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)  # GET /metrics


@app.get("/healthz")
def healthz():
    index = get_index()
    return {"status": "ok", "index_size": index.size, "dim": index.dim,
            "backend": get_settings().embedder_backend}


@app.post("/embed")
def embed(req: EmbedRequest):
    vecs = get_embedder().encode(req.texts)
    return {"vectors": vecs.tolist(), "dim": int(vecs.shape[1]) if vecs.size else get_embedder().dim}


@app.post("/index/add")
def index_add(req: IndexAddRequest):
    if len(req.ids) != len(req.texts):
        return {"error": "ids and texts length mismatch", "added": 0}
    vecs = get_embedder().encode(req.texts)
    index = get_index()
    index.add(req.ids, vecs)
    index.save()
    return {"added": len(req.ids), "index_size": index.size}


@app.post("/index/search")
def index_search(req: IndexSearchRequest):
    started = time.perf_counter()
    qvec = get_embedder().encode([req.query])[0]
    hits = get_index().search(np.asarray(qvec), top_k=req.top_k)
    latency_ms = (time.perf_counter() - started) * 1000
    return {
        "hits": [{"id": job_id, "score": score} for job_id, score in hits],
        "latency_ms": round(latency_ms, 3),
        "index_size": get_index().size,
    }


@app.post("/index/rebuild")
def index_rebuild():
    """Re-embed all jobs from the database and rebuild the index from scratch."""
    started = time.perf_counter()
    index = get_index()
    index.reset()
    embedder = get_embedder()
    total = 0
    with SessionLocal() as db:
        batch_size = 500
        offset = 0
        while True:
            jobs = db.query(Job).order_by(Job.id).offset(offset).limit(batch_size).all()
            if not jobs:
                break
            texts = [f"{j.title} at {j.company}. {j.description}" for j in jobs]
            vecs = embedder.encode(texts)
            index.add([j.id for j in jobs], vecs)
            for j in jobs:
                j.embedded = True
            db.commit()
            total += len(jobs)
            offset += batch_size
    index.save()
    return {"rebuilt": total, "index_size": index.size,
            "elapsed_s": round(time.perf_counter() - started, 2)}
