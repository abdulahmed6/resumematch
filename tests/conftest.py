"""Pytest configuration and fixtures for ResumeMatch tests.

Sets environment variables BEFORE importing any backend modules to ensure
proper test isolation of singletons and the SQLite database.
"""
import os
import tempfile

# Set environment variables BEFORE importing any backend module
_test_db_path = f"{tempfile.gettempdir()}/test_resumematch.db"
_test_index_path = f"{tempfile.gettempdir()}/test_faiss.index"

os.environ["RM_DATABASE_URL"] = f"sqlite:///{_test_db_path}"
os.environ["RM_CELERY_EAGER"] = "true"
os.environ["RM_EMBEDDING_URL"] = ""
os.environ["RM_FAISS_INDEX_PATH"] = _test_index_path

import pytest
from backend.common.database import SessionLocal, init_db, engine, Base
from backend.embedding.embedder import _embedder as embedder_module
from backend.embedding.index import _index as index_module
from backend.embedding.client import _client as client_module


@pytest.fixture(scope="function", autouse=True)
def reset_db():
    """Reset database and index files before each test."""
    # Drop all tables and recreate them
    Base.metadata.drop_all(bind=engine)
    init_db()

    # Remove persisted index file
    if os.path.exists(_test_index_path):
        os.remove(_test_index_path)

    yield

    # Cleanup after test
    Base.metadata.drop_all(bind=engine)
    if os.path.exists(_test_index_path):
        os.remove(_test_index_path)


@pytest.fixture(scope="function", autouse=True)
def reset_singletons():
    """Reset module-level singletons before each test."""
    import backend.embedding.embedder
    import backend.embedding.index
    import backend.embedding.client

    backend.embedding.embedder._embedder = None
    backend.embedding.index._index = None
    backend.embedding.client._client = None
    yield
    backend.embedding.embedder._embedder = None
    backend.embedding.index._index = None
    backend.embedding.client._client = None


@pytest.fixture
def db_session():
    """Provide a clean database session for tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
