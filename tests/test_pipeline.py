"""Tests for the end-to-end scraping and embedding pipeline."""
import pytest
from backend.common.database import SessionLocal
from backend.common.models import Job, ScrapeRun
from backend.scraper.tasks import scrape_source, index_jobs
from backend.embedding.client import get_embedding_client


class TestPipeline:
    """Test scrape_source task, deduplication, and indexing."""

    def test_scrape_source_creates_jobs(self, db_session):
        """scrape_source should fetch postings and create Job records."""
        result = scrape_source.delay(source_name="synthetic", count=10, seed=42)
        assert result.status == "SUCCESS"
        data = result.result

        assert data["found"] == 10
        assert data["new"] >= 0

        # Verify jobs exist in database
        jobs = db_session.query(Job).filter(Job.source == "synthetic").all()
        assert len(jobs) >= 1

    def test_scrape_run_recorded(self, db_session):
        """scrape_source should create a ScrapeRun record."""
        result = scrape_source.delay(source_name="synthetic", count=10, seed=42)
        data = result.result
        run_id = data["run_id"]

        # Verify ScrapeRun record
        run = db_session.query(ScrapeRun).filter(ScrapeRun.id == run_id).first()
        assert run is not None
        assert run.source == "synthetic"
        assert run.status == "done"
        assert run.jobs_found == 10
        assert run.jobs_new == data["new"]
        assert run.finished_at is not None

    def test_deduplication_same_seed(self, db_session):
        """Running scrape_source twice with same seed should not create duplicates."""
        # First run
        result1 = scrape_source.delay(source_name="synthetic", count=10, seed=42)
        data1 = result1.result
        new1 = data1["new"]

        # Second run with same seed
        result2 = scrape_source.delay(source_name="synthetic", count=10, seed=42)
        data2 = result2.result
        new2 = data2["new"]

        # Second run should have 0 new jobs (all duplicates)
        assert new2 == 0
        # Total jobs should be same as first run
        jobs = db_session.query(Job).filter(Job.source == "synthetic").all()
        assert len(jobs) == new1

    def test_jobs_marked_embedded(self, db_session):
        """Indexed jobs should have embedded=True."""
        result = scrape_source.delay(source_name="synthetic", count=5, seed=42)
        data = result.result

        # Get the created jobs
        jobs = db_session.query(Job).filter(Job.source == "synthetic").all()
        # In eager mode, all jobs should be indexed
        if data["indexed"] > 0:
            assert any(j.embedded for j in jobs)

    def test_index_jobs_task(self, db_session):
        """index_jobs task should embed and add to index."""
        # First create some jobs
        result = scrape_source.delay(source_name="synthetic", count=5, seed=42)
        data = result.result
        indexed_count = data["indexed"]

        # Index should have the jobs
        client = get_embedding_client()
        size = client.index_size()
        assert size == indexed_count

    def test_index_size_grows(self, db_session):
        """Running multiple scrapes should grow the index."""
        # First scrape
        result1 = scrape_source.delay(source_name="synthetic", count=5, seed=42)
        data1 = result1.result

        client = get_embedding_client()
        size1 = client.index_size()

        # Second scrape with different seed
        result2 = scrape_source.delay(source_name="synthetic", count=5, seed=43)
        data2 = result2.result

        size2 = client.index_size()

        # Size should have grown (if we added new jobs)
        if data2["new"] > 0:
            assert size2 > size1

    def test_skills_extracted_during_scrape(self, db_session):
        """Jobs created during scrape should have extracted skills."""
        result = scrape_source.delay(source_name="synthetic", count=5, seed=42)

        jobs = db_session.query(Job).filter(Job.source == "synthetic").all()
        for job in jobs:
            # All jobs should have some skills
            assert job.skills
            assert isinstance(job.skills, list)
            assert all(isinstance(s, str) for s in job.skills)

    def test_scrape_with_large_count(self, db_session):
        """Scrape should handle larger counts."""
        result = scrape_source.delay(source_name="synthetic", count=100, seed=42)
        data = result.result

        assert data["found"] == 100
        jobs = db_session.query(Job).filter(Job.source == "synthetic").all()
        assert len(jobs) == 100

    def test_scrape_idempotency(self, db_session):
        """Multiple identical scrapes should be idempotent (with same seed)."""
        for i in range(3):
            result = scrape_source.delay(source_name="synthetic", count=5, seed=99)
            data = result.result
            if i == 0:
                assert data["new"] == 5
            else:
                assert data["new"] == 0

        jobs = db_session.query(Job).filter(Job.source == "synthetic").all()
        assert len(jobs) == 5
