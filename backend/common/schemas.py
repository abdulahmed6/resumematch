"""Pydantic schemas shared by the API surface."""
from pydantic import BaseModel, Field


class JobOut(BaseModel):
    id: int
    external_id: str
    source: str
    title: str
    company: str
    location: str
    remote: bool
    salary_min: float | None = None
    salary_max: float | None = None
    seniority: str
    description: str
    skills: list[str] = []
    posted_at: str | None = None
    score: float | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=100)
    remote_only: bool = False
    seniority: str | None = None


class SearchResponse(BaseModel):
    query: str
    latency_ms: float
    total_indexed: int
    results: list[JobOut]


class SkillGapRequest(BaseModel):
    resume_text: str = Field(min_length=1)
    query: str | None = None
    top_k: int = Field(default=20, ge=1, le=100)


class SkillGapItem(BaseModel):
    skill: str
    frequency: int
    share: float  # fraction of matched jobs requiring this skill


class SkillGapResponse(BaseModel):
    resume_skills: list[str]
    matched_jobs: int
    coverage: float  # avg fraction of required skills the resume covers
    missing_skills: list[SkillGapItem]
    matched_skills: list[SkillGapItem]
    per_job: list[dict]


class ScrapeTriggerRequest(BaseModel):
    source: str = "synthetic"
    count: int = Field(default=350, ge=1, le=2000)


class StatsResponse(BaseModel):
    total_jobs: int
    total_indexed: int
    sources: dict[str, int]
    last_runs: list[dict]
    avg_query_latency_ms: float | None = None
