"""Scraper control-plane API.

Small FastAPI app used to trigger scrapes and inspect pipeline runs.
The heavy lifting happens in Celery workers.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from backend.common.database import get_db, init_db
from backend.common.models import ScrapeRun
from backend.common.schemas import ScrapeTriggerRequest
from backend.scraper.celery_app import celery_app
from backend.scraper.tasks import scrape_source


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ResumeMatch Scraper Service", lifespan=lifespan)


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
