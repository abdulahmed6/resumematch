"""Scraper control-plane API.

Small FastAPI app used to trigger scrapes and inspect pipeline runs.
The heavy lifting happens in Celery workers.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.orm import Session

from backend.common.database import get_db, init_db
from backend.common.models import ScrapeRun
from backend.common.schemas import ScrapeTriggerRequest
from backend.scraper import dlq
from backend.scraper.celery_app import celery_app
from backend.scraper.tasks import scrape_source


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ResumeMatch Scraper Service", lifespan=lifespan)
Instrumentator().instrument(app).expose(app)  # GET /metrics


@app.get("/healthz")
def healthz():
    return {"status": "ok", "eager": bool(celery_app.conf.task_always_eager)}


@app.post("/scrape")
def trigger_scrape(req: ScrapeTriggerRequest):
    result = scrape_source.delay(req.source, req.count)
    payload = {"queued": True, "task_id": result.id}
    if celery_app.conf.task_always_eager:
        payload.update({"queued": False, "result": result.result})
    return payload


@app.get("/runs")
def list_runs(limit: int = 20, db: Session = Depends(get_db)):
    runs = db.query(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(min(limit, 100)).all()
    return {"runs": [r.to_dict() for r in runs]}


@app.get("/dlq")
def list_dlq(limit: int = 50):
    """Inspect tasks that exhausted their retries (see scraper/dlq.py)."""
    return {"depth": dlq.dlq_length(), "entries": dlq.read_dlq(min(limit, 200))}


@app.post("/dlq/{entry_id}/replay")
def replay_dlq(entry_id: str):
    """Re-dispatch a dead-lettered task's original args and drop it from the DLQ."""
    try:
        return dlq.replay_dlq_entry(entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/dlq/{entry_id}")
def discard_dlq(entry_id: str):
    """Permanently discard a DLQ entry without replaying it."""
    removed = dlq.discard_dlq_entry(entry_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"no DLQ entry with id {entry_id}")
    return {"discarded": True}
