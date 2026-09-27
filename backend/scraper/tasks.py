"""Celery tasks: scrape -> persist -> embed+index.

`scrape_source` fans work out; each batch is deduplicated against the
database (source, external_id), enriched with extracted skills, then handed
to the embedding service to be added to the FAISS index.
"""
import socket
from datetime import datetime, timezone

from backend.common.database import SessionLocal, init_db
from backend.common.models import Job, ScrapeRun
from backend.common.skills import extract_skills
from backend.embedding.client import get_embedding_client
from backend.scraper.celery_app import celery_app
from backend.scraper.sources import get_source


def _embed_text(job: Job) -> str:
    return f"{job.title} at {job.company}. {job.description}"


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def scrape_source(self, source_name: str = "synthetic", count: int = 350, seed: int | None = None) -> dict:
    """Fetch postings from a source, upsert new ones, and index them."""
    init_db()
    worker = socket.gethostname()
    with SessionLocal() as db:
        run = ScrapeRun(source=source_name, worker=worker, status="running")
        db.add(run)
        db.commit()
        run_id = run.id

    try:
        source = get_source(source_name, seed=seed)
        postings = source.fetch(count)

        new_jobs: list[Job] = []
        with SessionLocal() as db:
            existing = {
                ext_id
                for (ext_id,) in db.query(Job.external_id).filter(Job.source == source_name).all()
            }
            for p in postings:
                if p.external_id in existing:
                    continue
                existing.add(p.external_id)
                skills = sorted(set(p.skills) | set(extract_skills(p.description)))
                job = Job(
                    external_id=p.external_id, source=source_name, title=p.title,
                    company=p.company, location=p.location, remote=p.remote,
                    seniority=p.seniority, salary_min=p.salary_min, salary_max=p.salary_max,
                    description=p.description, skills=skills, posted_at=p.posted_at,
                )
                db.add(job)
                new_jobs.append(job)
            db.commit()
            job_payload = [(j.id, _embed_text(j)) for j in new_jobs]

        indexed = 0
        if job_payload:
            ids = [jid for jid, _ in job_payload]
            texts = [txt for _, txt in job_payload]
            result = index_jobs.delay(ids, texts)
            # In eager mode the task already ran inline; in distributed mode it
            # was queued to the broker and a worker will pick it up.
            if celery_app.conf.task_always_eager:
                indexed = result.result or 0

        with SessionLocal() as db:
            run = db.get(ScrapeRun, run_id)
            run.status = "done"
            run.jobs_found = len(postings)
            run.jobs_new = len(new_jobs)
            run.finished_at = datetime.now(timezone.utc)
            db.commit()

        return {"run_id": run_id, "found": len(postings), "new": len(new_jobs), "indexed": indexed}

    except Exception as exc:  # noqa: BLE001
        with SessionLocal() as db:
            run = db.get(ScrapeRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = str(exc)[:2000]
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=15)
def index_jobs(self, ids: list[int], texts: list[str]) -> int:
    """Embed job texts and upsert them into the FAISS index."""
    try:
        client = get_embedding_client()
        added = client.index_add(ids, texts)
        with SessionLocal() as db:
            db.query(Job).filter(Job.id.in_(ids)).update({Job.embedded: True}, synchronize_session=False)
            db.commit()
        return added
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc)
