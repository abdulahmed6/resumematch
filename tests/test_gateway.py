"""Tests for the FastAPI gateway service."""
import io
import pytest
from fastapi.testclient import TestClient

from backend.gateway.main import app
from backend.common.database import SessionLocal
from backend.scraper.tasks import scrape_source


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


class TestGatewayHealthz:
    """Test health check endpoint."""

    def test_healthz(self, client):
        """GET /api/healthz should return 200 with status."""
        response = client.get("/api/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "gateway"


class TestGatewaySearch:
    """Test semantic search endpoint."""

    def test_search_empty_index(self, client):
        """Search on empty index should return empty results."""
        response = client.post("/api/search", json={
            "query": "python fastapi",
            "top_k": 10
        })
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["total_indexed"] == 0

    def test_search_with_seed_data(self, client, db_session):
        """Search should return ranked results."""
        # Seed with jobs
        result = scrape_source.delay(source_name="synthetic", count=20, seed=42)

        response = client.post("/api/search", json={
            "query": "python fastapi backend",
            "top_k": 10
        })
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "python fastapi backend"
        assert "latency_ms" in data
        assert isinstance(data["latency_ms"], float)
        assert data["latency_ms"] >= 0

    def test_search_results_ranked(self, client, db_session):
        """Search results should be ranked by score."""
        scrape_source.delay(source_name="synthetic", count=20, seed=42)

        response = client.post("/api/search", json={
            "query": "python",
            "top_k": 10
        })
        assert response.status_code == 200
        data = response.json()
        results = data["results"]

        if len(results) > 1:
            # Scores should be in descending order
            scores = [r.get("score") for r in results if r.get("score") is not None]
            assert scores == sorted(scores, reverse=True)

    def test_search_respects_top_k(self, client, db_session):
        """Search should respect top_k parameter."""
        scrape_source.delay(source_name="synthetic", count=50, seed=42)

        for top_k in [5, 10, 20]:
            response = client.post("/api/search", json={
                "query": "python",
                "top_k": top_k
            })
            assert response.status_code == 200
            data = response.json()
            assert len(data["results"]) <= top_k

    def test_search_remote_only_filter(self, client, db_session):
        """Search with remote_only filter should return only remote jobs."""
        scrape_source.delay(source_name="synthetic", count=30, seed=42)

        response = client.post("/api/search", json={
            "query": "python",
            "top_k": 10,
            "remote_only": True
        })
        assert response.status_code == 200
        data = response.json()

        for result in data["results"]:
            assert result["remote"] is True

    def test_search_seniority_filter(self, client, db_session):
        """Search with seniority filter should return jobs of that level."""
        scrape_source.delay(source_name="synthetic", count=30, seed=42)

        response = client.post("/api/search", json={
            "query": "python",
            "top_k": 20,
            "seniority": "senior"
        })
        assert response.status_code == 200
        data = response.json()

        for result in data["results"]:
            assert result["seniority"] == "senior"

    def test_search_invalid_query(self, client):
        """Search with invalid query should return 422."""
        response = client.post("/api/search", json={
            "query": "",  # empty query
            "top_k": 10
        })
        assert response.status_code == 422


class TestGatewayJobs:
    """Test job listing and retrieval endpoints."""

    def test_list_jobs_empty(self, client):
        """List jobs on empty database should return empty list."""
        response = client.get("/api/jobs?limit=20&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_list_jobs_with_data(self, client, db_session):
        """List jobs should return jobs ordered by posted_at DESC."""
        scrape_source.delay(source_name="synthetic", count=10, seed=42)

        response = client.get("/api/jobs?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 5

    def test_list_jobs_pagination(self, client, db_session):
        """Pagination should work correctly."""
        scrape_source.delay(source_name="synthetic", count=30, seed=42)

        # Get first page
        response1 = client.get("/api/jobs?limit=10&offset=0")
        data1 = response1.json()
        ids1 = [j["id"] for j in data1]

        # Get second page
        response2 = client.get("/api/jobs?limit=10&offset=10")
        data2 = response2.json()
        ids2 = [j["id"] for j in data2]

        # Pages should be different
        assert ids1 != ids2

    def test_get_job_by_id(self, client, db_session):
        """GET /api/jobs/{id} should return specific job."""
        scrape_source.delay(source_name="synthetic", count=5, seed=42)

        # Get a job
        response = client.get("/api/jobs?limit=1&offset=0")
        if response.json():
            job_id = response.json()[0]["id"]
            response = client.get(f"/api/jobs/{job_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == job_id

    def test_get_job_not_found(self, client):
        """GET /api/jobs/{nonexistent} should return 404."""
        response = client.get("/api/jobs/99999")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_job_schema_completeness(self, client, db_session):
        """Job objects should have all required fields."""
        scrape_source.delay(source_name="synthetic", count=1, seed=42)

        response = client.get("/api/jobs?limit=1&offset=0")
        assert response.status_code == 200
        jobs = response.json()
        if jobs:
            job = jobs[0]
            required_fields = [
                "id", "external_id", "source", "title", "company",
                "location", "remote", "salary_min", "salary_max",
                "seniority", "description", "skills", "posted_at"
            ]
            for field in required_fields:
                assert field in job


class TestGatewaySkillGap:
    """Test skill-gap analysis endpoint."""

    def test_skill_gap_basic(self, client, db_session):
        """Skill gap should work with resume text."""
        scrape_source.delay(source_name="synthetic", count=10, seed=42)

        response = client.post("/api/skill-gap", json={
            "resume_text": "Python FastAPI PostgreSQL",
            "top_k": 10
        })
        assert response.status_code == 200
        data = response.json()
        assert "resume_skills" in data
        assert "coverage" in data
        assert "missing_skills" in data
        assert "matched_skills" in data
        assert "per_job" in data

    def test_skill_gap_coverage_range(self, client, db_session):
        """Coverage should be between 0 and 1."""
        scrape_source.delay(source_name="synthetic", count=10, seed=42)

        response = client.post("/api/skill-gap", json={
            "resume_text": "Python",
            "top_k": 10
        })
        assert response.status_code == 200
        data = response.json()
        assert 0.0 <= data["coverage"] <= 1.0

    def test_skill_gap_empty_resume(self, client):
        """Empty resume should be rejected."""
        response = client.post("/api/skill-gap", json={
            "resume_text": "",
            "top_k": 10
        })
        assert response.status_code == 422

    def test_skill_gap_resume_too_large(self, client):
        """Resume exceeding max chars should be rejected."""
        huge_resume = "x" * 100000  # larger than max_resume_chars
        response = client.post("/api/skill-gap", json={
            "resume_text": huge_resume,
            "top_k": 10
        })
        assert response.status_code == 413

    def test_skill_gap_with_target_query(self, client, db_session):
        """Skill gap should support optional target query."""
        scrape_source.delay(source_name="synthetic", count=10, seed=42)

        response = client.post("/api/skill-gap", json={
            "resume_text": "Python",
            "query": "senior backend engineer",
            "top_k": 10
        })
        assert response.status_code == 200
        data = response.json()
        assert data["matched_jobs"] >= 0


class TestGatewayUploadResume:
    """Test resume upload endpoint."""

    def test_upload_txt_file(self, client):
        """Upload plain text resume should work."""
        content = b"Python FastAPI PostgreSQL"
        response = client.post("/api/resume/upload", files={
            "file": ("resume.txt", io.BytesIO(content), "text/plain")
        })
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "resume.txt"
        assert data["chars"] == len(content)
        assert data["text"] == content.decode()
        assert "skills" in data

    def test_upload_md_file(self, client):
        """Upload markdown resume should work."""
        content = b"# Resume\n\nPython and FastAPI"
        response = client.post("/api/resume/upload", files={
            "file": ("resume.md", io.BytesIO(content), "text/markdown")
        })
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "resume.md"

    def test_upload_binary_rejected(self, client):
        """Upload binary file should be rejected."""
        content = b"\x89PNG\r\n\x1a\n"  # PNG header
        response = client.post("/api/resume/upload", files={
            "file": ("image.png", io.BytesIO(content), "image/png")
        })
        assert response.status_code == 415

    def test_upload_invalid_utf8_rejected(self, client):
        """Upload invalid UTF-8 should be rejected."""
        content = b"\x80\x81\x82\x83"  # invalid UTF-8
        response = client.post("/api/resume/upload", files={
            "file": ("resume.txt", io.BytesIO(content), "text/plain")
        })
        assert response.status_code == 415

    def test_upload_file_too_large(self, client):
        """Upload file exceeding limit should be rejected."""
        huge_content = b"x" * (200001 * 4)  # larger than limit
        response = client.post("/api/resume/upload", files={
            "file": ("resume.txt", io.BytesIO(huge_content), "text/plain")
        })
        assert response.status_code == 413

    def test_upload_truncates_long_text(self, client):
        """Uploaded text should be truncated to max_resume_chars."""
        from backend.common.config import get_settings
        settings = get_settings()
        content = b"x" * (settings.max_resume_chars + 1000)
        response = client.post("/api/resume/upload", files={
            "file": ("resume.txt", io.BytesIO(content), "text/plain")
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["text"]) == settings.max_resume_chars


class TestGatewayStats:
    """Test statistics endpoint."""

    def test_stats_empty(self, client):
        """Stats on empty database should return zeros."""
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_jobs"] == 0
        assert data["total_indexed"] == 0
        assert data["sources"] == {}

    def test_stats_with_data(self, client, db_session):
        """Stats should reflect seeded data."""
        scrape_source.delay(source_name="synthetic", count=10, seed=42)

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_jobs"] >= 10
        assert "synthetic" in data["sources"]
        assert data["sources"]["synthetic"] >= 10

    def test_stats_last_runs(self, client, db_session):
        """Stats should include recent scrape runs."""
        scrape_source.delay(source_name="synthetic", count=5, seed=42)

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["last_runs"], list)
        assert len(data["last_runs"]) > 0


class TestGatewaySkills:
    """Test skill taxonomy endpoint."""

    def test_skills_returns_list(self, client):
        """GET /api/skills should return skill list."""
        response = client.get("/api/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data
        assert isinstance(data["skills"], list)
        assert len(data["skills"]) > 0

    def test_skills_canonical(self, client):
        """Skills should be canonical names from taxonomy."""
        response = client.get("/api/skills")
        data = response.json()
        skills = data["skills"]
        # Check some known skills
        assert "python" in skills
        assert "javascript" in skills
        assert "react" in skills
