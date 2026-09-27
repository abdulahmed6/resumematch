"""Tests for the embedding microservice FastAPI app.

This app had no dedicated test coverage before; added while touching it to
wire in Prometheus instrumentation (see backend/embedding/service.py), to
make sure /embed, /index/add, /index/search, /index/rebuild and the new
/metrics endpoint all still work end-to-end.
"""
import pytest
from fastapi.testclient import TestClient

from backend.embedding.service import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthz:
    def test_healthz(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["index_size"] == 0
        assert data["dim"] > 0


class TestEmbed:
    def test_embed_returns_vectors(self, client):
        response = client.post("/embed", json={"texts": ["python backend engineer"]})
        assert response.status_code == 200
        data = response.json()
        assert len(data["vectors"]) == 1
        assert len(data["vectors"][0]) == data["dim"]

    def test_embed_multiple_texts(self, client):
        response = client.post("/embed", json={"texts": ["foo", "bar", "baz"]})
        assert response.status_code == 200
        assert len(response.json()["vectors"]) == 3


class TestIndexAddAndSearch:
    def test_add_then_search(self, client):
        add_resp = client.post("/index/add", json={
            "ids": [1, 2, 3],
            "texts": [
                "python backend engineer fastapi postgres",
                "react frontend engineer typescript",
                "devops engineer kubernetes terraform",
            ],
        })
        assert add_resp.status_code == 200
        assert add_resp.json()["added"] == 3
        assert add_resp.json()["index_size"] == 3

        search_resp = client.post("/index/search", json={
            "query": "python fastapi backend", "top_k": 2,
        })
        assert search_resp.status_code == 200
        data = search_resp.json()
        assert len(data["hits"]) == 2
        assert data["index_size"] == 3
        assert "latency_ms" in data

    def test_add_mismatched_lengths_returns_error(self, client):
        response = client.post("/index/add", json={"ids": [1, 2], "texts": ["only one"]})
        assert response.status_code == 200
        assert response.json()["added"] == 0
        assert "error" in response.json()

    def test_search_empty_index(self, client):
        response = client.post("/index/search", json={"query": "anything", "top_k": 5})
        assert response.status_code == 200
        assert response.json()["hits"] == []


class TestIndexRebuild:
    def test_rebuild_from_database(self, client, db_session):
        from backend.scraper.tasks import scrape_source

        scrape_source.delay(source_name="synthetic", count=5, seed=42)

        response = client.post("/index/rebuild")
        assert response.status_code == 200
        data = response.json()
        assert data["rebuilt"] == 5
        assert data["index_size"] == 5


class TestMetricsEndpoint:
    def test_metrics_exposed(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert b"# HELP" in response.content
