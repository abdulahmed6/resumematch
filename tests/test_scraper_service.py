"""Tests for the scraper control-plane FastAPI service, including the DLQ
inspect/replay/discard endpoints backed by fakeredis.
"""
import pytest
from fastapi.testclient import TestClient

import backend.scraper.dlq as dlq
from backend.scraper.service import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthz:
    def test_healthz(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["eager"] is True


class TestTriggerScrape:
    def test_trigger_scrape_runs_eagerly(self, client, db_session):
        response = client.post("/scrape", json={"source": "synthetic", "count": 5})
        assert response.status_code == 200
        data = response.json()
        assert data["queued"] is False
        assert data["result"]["found"] == 5


class TestListRuns:
    def test_list_runs(self, client, db_session):
        client.post("/scrape", json={"source": "synthetic", "count": 5})
        response = client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) >= 1
        assert data["runs"][0]["source"] == "synthetic"


class TestDlqEndpoints:
    def test_list_dlq_empty(self, client):
        response = client.get("/dlq")
        assert response.status_code == 200
        data = response.json()
        assert data == {"depth": 0, "entries": []}

    def test_list_dlq_with_entries(self, client):
        dlq.push_to_dlq(task_name="t1", args={"a": 1}, error="err1")
        dlq.push_to_dlq(task_name="t2", args={"a": 2}, error="err2")

        response = client.get("/dlq")
        assert response.status_code == 200
        data = response.json()
        assert data["depth"] == 2
        assert len(data["entries"]) == 2
        assert data["entries"][0]["task"] == "t2"  # most recent first

    def test_list_dlq_respects_limit(self, client):
        for i in range(5):
            dlq.push_to_dlq(task_name="t", args={"n": i}, error="e")
        response = client.get("/dlq", params={"limit": 2})
        assert response.status_code == 200
        assert len(response.json()["entries"]) == 2

    def test_replay_dlq_entry(self, client, db_session):
        entry_id = dlq.push_to_dlq(
            task_name="backend.scraper.tasks.index_jobs",
            args={"ids": [], "texts": []},
            error="simulated failure",
        )

        response = client.post(f"/dlq/{entry_id}/replay")
        assert response.status_code == 200
        data = response.json()
        assert data["replayed"] is True
        assert data["task"] == "backend.scraper.tasks.index_jobs"

        # entry should be gone, and the DLQ empty again
        assert client.get("/dlq").json() == {"depth": 0, "entries": []}

    def test_replay_missing_entry_returns_404(self, client):
        response = client.post("/dlq/0-0/replay")
        assert response.status_code == 404

    def test_discard_dlq_entry(self, client):
        entry_id = dlq.push_to_dlq(task_name="t", args={}, error="e")
        response = client.delete(f"/dlq/{entry_id}")
        assert response.status_code == 200
        assert response.json() == {"discarded": True}
        assert dlq.dlq_length() == 0

    def test_discard_missing_entry_returns_404(self, client):
        response = client.delete("/dlq/0-0")
        assert response.status_code == 404


class TestMetricsEndpoint:
    def test_metrics_exposed(self, client):
        """Instrumentator should expose a Prometheus /metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert b"# HELP" in response.content
