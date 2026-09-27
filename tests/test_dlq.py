"""Tests for the Redis-Streams-backed dead-letter queue.

Covers the DLQ module's round-trip behavior (push/read/get/discard) and the
integration path where a Celery task that exhausts its retries lands in the
DLQ. The `fake_redis` fixture (tests/conftest.py) swaps the DLQ's Redis
client for an in-memory fakeredis instance, so no real Redis is required.

Note on Celery eager mode: `task.delay(...)` cannot naturally trigger the
"retries exhausted" branch, because `self.retry()` in eager mode raises
`Retry` immediately on the first call rather than looping. To deterministically
test that branch we use `task.push_request(retries=task.max_retries)` to make
the task believe it's already on its last attempt, then invoke the task
directly (not via `.delay()`) so that request state is honored.
"""
import pytest

import backend.scraper.dlq as dlq
from backend.common.models import ScrapeRun
from backend.scraper.tasks import index_jobs, scrape_source


class TestDlqRoundTrip:
    """Basic push/read/get/discard behavior against the fake Redis stream."""

    def test_push_and_read(self):
        entry_id = dlq.push_to_dlq(
            task_name="some.task", args={"x": 1}, error="boom", run_id=7
        )
        assert entry_id

        entries = dlq.read_dlq()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["id"] == entry_id
        assert entry["task"] == "some.task"
        assert entry["args"] == {"x": 1}
        assert entry["error"] == "boom"
        assert entry["run_id"] == 7
        assert isinstance(entry["failed_at"], float)

    def test_push_without_run_id(self):
        entry_id = dlq.push_to_dlq(task_name="t", args={}, error="e")
        entry = dlq.get_dlq_entry(entry_id)
        assert entry["run_id"] is None

    def test_dlq_length(self):
        assert dlq.dlq_length() == 0
        dlq.push_to_dlq(task_name="t", args={}, error="e1")
        dlq.push_to_dlq(task_name="t", args={}, error="e2")
        assert dlq.dlq_length() == 2

    def test_read_dlq_most_recent_first(self):
        id1 = dlq.push_to_dlq(task_name="t", args={"n": 1}, error="e1")
        id2 = dlq.push_to_dlq(task_name="t", args={"n": 2}, error="e2")
        entries = dlq.read_dlq()
        assert [e["id"] for e in entries] == [id2, id1]

    def test_read_dlq_respects_count(self):
        for i in range(5):
            dlq.push_to_dlq(task_name="t", args={"n": i}, error="e")
        entries = dlq.read_dlq(count=2)
        assert len(entries) == 2

    def test_get_dlq_entry_missing_returns_none(self):
        assert dlq.get_dlq_entry("0-0") is None

    def test_discard_dlq_entry(self):
        entry_id = dlq.push_to_dlq(task_name="t", args={}, error="e")
        assert dlq.discard_dlq_entry(entry_id) is True
        assert dlq.dlq_length() == 0
        assert dlq.get_dlq_entry(entry_id) is None

    def test_discard_missing_entry_returns_false(self):
        assert dlq.discard_dlq_entry("0-0") is False

    def test_error_truncated_to_2000_chars(self):
        entry_id = dlq.push_to_dlq(task_name="t", args={}, error="x" * 5000)
        entry = dlq.get_dlq_entry(entry_id)
        assert len(entry["error"]) == 2000


class TestDlqReplay:
    """replay_dlq_entry() re-dispatches through Celery and clears the entry."""

    def test_replay_runs_task_and_discards_entry(self, db_session):
        entry_id = dlq.push_to_dlq(
            task_name="backend.scraper.tasks.index_jobs",
            args={"ids": [], "texts": []},
            error="simulated failure",
        )

        result = dlq.replay_dlq_entry(entry_id)

        assert result["replayed"] is True
        assert result["task"] == "backend.scraper.tasks.index_jobs"
        assert result["new_task_id"]
        # entry should be gone after a successful replay
        assert dlq.get_dlq_entry(entry_id) is None
        assert dlq.dlq_length() == 0

    def test_replay_missing_entry_raises_keyerror(self):
        with pytest.raises(KeyError):
            dlq.replay_dlq_entry("0-0")

    def test_replay_does_not_hang_or_touch_real_broker(self, db_session):
        """Regression test: replay must use apply_async (eager-aware), not
        send_task (which ignores task_always_eager and opens a real broker
        connection). This test would hang/fail if that regressed, since no
        real Redis broker is reachable in the test environment.
        """
        entry_id = dlq.push_to_dlq(
            task_name="backend.scraper.tasks.index_jobs",
            args={"ids": [], "texts": []},
            error="e",
        )
        result = dlq.replay_dlq_entry(entry_id)
        # In eager mode the result is already available synchronously.
        assert result["new_task_id"]


class TestRetryExhaustionPushesToDlq:
    """Integration: a task that exhausts its retries lands in the DLQ."""

    def test_scrape_source_exhausted_retries_pushed_to_dlq(self, db_session):
        assert dlq.dlq_length() == 0

        scrape_source.push_request(retries=scrape_source.max_retries)
        try:
            with pytest.raises(ValueError):
                scrape_source(source_name="does-not-exist", count=5, seed=1)
        finally:
            scrape_source.pop_request()

        assert dlq.dlq_length() == 1
        entries = dlq.read_dlq()
        assert entries[0]["task"] == "backend.scraper.tasks.scrape_source"
        assert entries[0]["args"] == {
            "source_name": "does-not-exist", "count": 5, "seed": 1,
        }
        assert "unknown source" in entries[0]["error"]

    def test_scrape_source_exhausted_retries_marks_run_failed(self, db_session):
        scrape_source.push_request(retries=scrape_source.max_retries)
        try:
            with pytest.raises(ValueError):
                scrape_source(source_name="does-not-exist", count=5, seed=1)
        finally:
            scrape_source.pop_request()

        run = db_session.query(ScrapeRun).order_by(ScrapeRun.id.desc()).first()
        assert run.status == "failed"
        assert "unknown source" in run.error

    def test_scrape_source_not_yet_exhausted_does_not_push_to_dlq(self, db_session):
        """Before the final retry, the task takes the retry branch (not the
        DLQ branch), even though calling the task directly (rather than via
        .apply()/.delay()) makes Celery re-raise the original exception
        instead of actually scheduling a delayed retry -- see
        Task.retry()'s `request.called_directly` short-circuit. The
        important thing here is *which branch* of our own except-block ran,
        which we can observe via the DLQ staying empty and the ScrapeRun
        being marked failed without ever calling push_to_dlq.
        """
        scrape_source.push_request(retries=0)  # first attempt, well under max_retries
        try:
            with pytest.raises(ValueError):
                scrape_source(source_name="does-not-exist", count=5, seed=1)
        finally:
            scrape_source.pop_request()

        assert dlq.dlq_length() == 0

    def test_index_jobs_exhausted_retries_pushed_to_dlq(self, db_session, monkeypatch):
        """Force index_jobs' embedding call to fail, then verify DLQ push."""
        import backend.scraper.tasks as tasks_module

        def _boom(*args, **kwargs):
            raise RuntimeError("embedding backend unreachable")

        monkeypatch.setattr(
            tasks_module, "get_embedding_client", lambda: type(
                "Broken", (), {"index_add": staticmethod(_boom)}
            )()
        )

        index_jobs.push_request(retries=index_jobs.max_retries)
        try:
            with pytest.raises(RuntimeError):
                index_jobs(ids=[1, 2], texts=["a", "b"])
        finally:
            index_jobs.pop_request()

        assert dlq.dlq_length() == 1
        entry = dlq.read_dlq()[0]
        assert entry["task"] == "backend.scraper.tasks.index_jobs"
        assert entry["args"] == {"ids": [1, 2], "texts": ["a", "b"]}
