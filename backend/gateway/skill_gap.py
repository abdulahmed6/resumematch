"""Skill-gap analysis.

Given a resume and a set of matched job postings, compute:
- which taxonomy skills the resume demonstrates,
- which required skills are missing and how often they appear,
- a per-job coverage score (fraction of the job's skills the resume covers).
"""
from collections import Counter

from backend.common.models import Job
from backend.common.skills import extract_skills


def analyze_skill_gap(resume_text: str, jobs: list[Job]) -> dict:
    resume_skills = set(extract_skills(resume_text))

    missing_counter: Counter[str] = Counter()
    matched_counter: Counter[str] = Counter()
    per_job: list[dict] = []
    coverage_sum = 0.0
    jobs_with_skills = 0

    for job in jobs:
        job_skills = set(job.skills or [])
        if not job_skills:
            per_job.append({
                "job_id": job.id, "title": job.title, "company": job.company,
                "coverage": None, "missing": [], "matched": [],
            })
            continue
        matched = sorted(job_skills & resume_skills)
        missing = sorted(job_skills - resume_skills)
        coverage = len(matched) / len(job_skills)
        coverage_sum += coverage
        jobs_with_skills += 1
        missing_counter.update(missing)
        matched_counter.update(matched)
        per_job.append({
            "job_id": job.id, "title": job.title, "company": job.company,
            "coverage": round(coverage, 3), "missing": missing, "matched": matched,
        })

    n = max(jobs_with_skills, 1)
    return {
        "resume_skills": sorted(resume_skills),
        "matched_jobs": len(jobs),
        "coverage": round(coverage_sum / n, 3) if jobs_with_skills else 0.0,
        "missing_skills": [
            {"skill": s, "frequency": c, "share": round(c / n, 3)}
            for s, c in missing_counter.most_common()
        ],
        "matched_skills": [
            {"skill": s, "frequency": c, "share": round(c / n, 3)}
            for s, c in matched_counter.most_common()
        ],
        "per_job": per_job,
    }
