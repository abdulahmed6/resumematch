"""Central configuration for all ResumeMatch services.

Every service (gateway, scraper, embedding) reads from this single settings
object so that environment handling is consistent across the microservices.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RM_", extra="ignore")

    # --- environment -------------------------------------------------------
    env: str = "dev"  # dev | prod

    # --- database ----------------------------------------------------------
    # dev default: local SQLite file. prod (docker-compose): postgres DSN.
    database_url: str = "sqlite:///./resumematch.db"

    # --- redis / celery ----------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    # When True, Celery tasks execute synchronously in-process (no broker
    # needed). Used for local dev and tests.
    celery_eager: bool = True

    # --- embedding service --------------------------------------------------
    # If set, the gateway/scraper call the embedding microservice over HTTP.
    # If empty, they fall back to an in-process embedder (dev convenience).
    embedding_url: str = ""
    embedder_backend: str = "hashing"  # hashing | sentence-transformers
    embedding_dim: int = 384
    faiss_index_path: str = "./data/faiss.index"

    # --- scraping ----------------------------------------------------------
    scrape_batch_size: int = 350       # postings per worker batch
    scrape_interval_minutes: int = 60  # celery-beat schedule

    # --- api ---------------------------------------------------------------
    cors_origins: str = "*"
    max_resume_chars: int = 50_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
