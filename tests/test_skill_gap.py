"""Tests for skill-gap analysis."""
import pytest

from backend.common.models import Job
from backend.gateway.skill_gap import analyze_skill_gap


class TestAnalyzeSkillGap:
    """Test skill-gap analysis with various job and resume combinations."""

    def test_full_coverage(self):
        """Resume covering all job skills should have 100% coverage."""
        resume_text = "Python FastAPI PostgreSQL Docker"
        job = Job(
            id=1, external_id="j1", source="test", title="Backend Engineer",
            company="Test Co", description="Backend role", skills=["python", "fastapi", "postgresql", "docker"]
        )

        result = analyze_skill_gap(resume_text, [job])

        assert result["coverage"] == 1.0
        assert len(result["missing_skills"]) == 0
        assert len(result["matched_skills"]) == 4

    def test_zero_coverage(self):
        """Resume with no job skills should have 0% coverage."""
        resume_text = "Java Spring Boot"
        job = Job(
            id=1, external_id="j1", source="test", title="Backend Engineer",
            company="Test Co", description="Backend role", skills=["python", "fastapi", "postgresql"]
        )

        result = analyze_skill_gap(resume_text, [job])

        assert result["coverage"] == 0.0
        assert len(result["missing_skills"]) == 3
        assert len(result["matched_skills"]) == 0

    def test_partial_coverage(self):
        """Resume with some job skills should have partial coverage."""
        resume_text = "Python PostgreSQL"
        job = Job(
            id=1, external_id="j1", source="test", title="Backend Engineer",
            company="Test Co", description="Backend role", skills=["python", "fastapi", "postgresql", "docker"]
        )

        result = analyze_skill_gap(resume_text, [job])

        assert result["coverage"] == 0.5  # 2 out of 4 skills
        assert len(result["missing_skills"]) == 2
        assert len(result["matched_skills"]) == 2

    def test_empty_resume(self):
        """Empty resume should have no skills."""
        resume_text = ""
        job = Job(
            id=1, external_id="j1", source="test", title="Backend Engineer",
            company="Test Co", description="Backend role", skills=["python", "fastapi"]
        )

        result = analyze_skill_gap(resume_text, [job])

        assert result["resume_skills"] == []
        assert result["coverage"] == 0.0
        assert len(result["missing_skills"]) == 2

    def test_job_with_no_skills(self):
        """Job with no skills should not affect coverage calculation."""
        resume_text = "Python FastAPI"
        job = Job(
            id=1, external_id="j1", source="test", title="Backend Engineer",
            company="Test Co", description="Backend role", skills=[]
        )

        result = analyze_skill_gap(resume_text, [job])

        # Coverage should be None for jobs without skills
        assert any(p["coverage"] is None for p in result["per_job"])
        # But overall coverage should still be 0 (no jobs with skills)
        assert result["coverage"] == 0.0

    def test_multiple_jobs(self):
        """Multiple jobs should aggregate skill stats."""
        resume_text = "Python Docker"
        jobs = [
            Job(
                id=1, external_id="j1", source="test", title="Backend Engineer",
                company="Company A", description="Role", skills=["python", "fastapi"]
            ),
            Job(
                id=2, external_id="j2", source="test", title="DevOps Engineer",
                company="Company B", description="Role", skills=["docker", "kubernetes"]
            ),
        ]

        result = analyze_skill_gap(resume_text, jobs)

        assert result["matched_jobs"] == 2
        assert len(result["matched_skills"]) == 2  # python, docker
        assert len(result["missing_skills"]) == 2  # fastapi, kubernetes
        # Average coverage: (1/2 + 1/2) / 2 = 0.5
        assert result["coverage"] == 0.5

    def test_missing_skills_frequency(self):
        """Missing skills should have correct frequency counts."""
        resume_text = "Python"
        jobs = [
            Job(
                id=1, external_id="j1", source="test", title="Role1",
                company="Company A", description="Role", skills=["python", "fastapi", "postgresql"]
            ),
            Job(
                id=2, external_id="j2", source="test", title="Role2",
                company="Company B", description="Role", skills=["python", "fastapi", "docker"]
            ),
        ]

        result = analyze_skill_gap(resume_text, jobs)

        missing = {s["skill"]: s["frequency"] for s in result["missing_skills"]}
        assert missing["fastapi"] == 2  # appears in both jobs
        assert missing["postgresql"] == 1
        assert missing["docker"] == 1

    def test_matched_skills_share(self):
        """Matched skills should have correct share calculation."""
        resume_text = "Python FastAPI"
        jobs = [
            Job(
                id=1, external_id="j1", source="test", title="Role1",
                company="Company A", description="Role", skills=["python", "fastapi"]
            ),
            Job(
                id=2, external_id="j2", source="test", title="Role2",
                company="Company B", description="Role", skills=["python", "fastapi"]
            ),
        ]

        result = analyze_skill_gap(resume_text, jobs)

        matched = {s["skill"]: s["share"] for s in result["matched_skills"]}
        # Both skills appear in both jobs
        assert matched["python"] == 1.0  # 2/2 jobs
        assert matched["fastapi"] == 1.0  # 2/2 jobs

    def test_per_job_details(self):
        """Per-job details should include coverage and skill breakdown."""
        resume_text = "Python FastAPI"
        job = Job(
            id=42, external_id="j42", source="test", title="Backend Engineer",
            company="Test Co", description="Role", skills=["python", "fastapi", "postgresql"]
        )

        result = analyze_skill_gap(resume_text, [job])

        job_detail = result["per_job"][0]
        assert job_detail["job_id"] == 42
        assert job_detail["title"] == "Backend Engineer"
        assert job_detail["company"] == "Test Co"
        assert job_detail["coverage"] == round(2/3, 3)
        assert set(job_detail["matched"]) == {"python", "fastapi"}
        assert job_detail["missing"] == ["postgresql"]

    def test_resume_skills_extracted(self):
        """Resume text should be parsed for skills."""
        resume_text = "Expertise: Python, JavaScript, React, Docker and Kubernetes"
        jobs = []

        result = analyze_skill_gap(resume_text, jobs)

        # Should extract skills from resume
        assert "python" in result["resume_skills"]
        assert "javascript" in result["resume_skills"]
        assert "react" in result["resume_skills"]
        assert "docker" in result["resume_skills"]
        assert "kubernetes" in result["resume_skills"]

    def test_empty_jobs_list(self):
        """Empty jobs list should handle gracefully."""
        resume_text = "Python FastAPI"
        result = analyze_skill_gap(resume_text, [])

        assert result["matched_jobs"] == 0
        assert result["coverage"] == 0.0
        assert len(result["per_job"]) == 0
        assert len(result["missing_skills"]) == 0
        assert len(result["matched_skills"]) == 0

    def test_all_jobs_no_skills(self):
        """Jobs without skills should be handled."""
        resume_text = "Python"
        jobs = [
            Job(
                id=1, external_id="j1", source="test", title="Role1",
                company="Company A", description="Role", skills=[]
            ),
            Job(
                id=2, external_id="j2", source="test", title="Role2",
                company="Company B", description="Role", skills=[]
            ),
        ]

        result = analyze_skill_gap(resume_text, jobs)

        assert result["matched_jobs"] == 2
        assert result["coverage"] == 0.0  # No jobs with skills to cover
        assert all(p["coverage"] is None for p in result["per_job"])
