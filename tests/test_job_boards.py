"""Tests for the Greenhouse and Lever sources.

The payloads below are hand-written in the shape of each public API's
documented response (they are not recorded from a live board), and are served
through httpx.MockTransport so the tests never touch the network.
"""
import httpx
import pytest

from backend.scraper.job_boards import (
    GreenhouseSource,
    LeverSource,
    html_to_text,
    infer_seniority,
)
from backend.scraper.sources import get_source

GREENHOUSE_PAYLOAD = {
    "jobs": [
        {
            "id": 4012345,
            "title": "Senior Backend Engineer, Payments",
            "company_name": "Acme",
            "location": {"name": "Remote - US"},
            "updated_at": "2026-11-20T15:04:05-05:00",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/4012345",
            # Greenhouse returns HTML that is entity-escaped once more.
            "content": "&lt;p&gt;Build APIs in &lt;strong&gt;Python&lt;/strong&gt; and PostgreSQL.&lt;/p&gt;"
                       "&lt;ul&gt;&lt;li&gt;Docker &amp;amp; Kubernetes&lt;/li&gt;&lt;/ul&gt;",
        },
        {
            "id": 4012346,
            "title": "Software Engineering Intern",
            "location": {"name": "Minneapolis, MN"},
            "updated_at": "2026-11-21T09:00:00Z",
            "content": "&lt;p&gt;Summer internship working with React.&lt;/p&gt;",
        },
        {"id": 4012347, "title": "", "location": {"name": "NYC"}, "content": ""},  # skipped
    ]
}

LEVER_PAYLOAD = [
    {
        "id": "a1b2c3d4-0000-1111-2222-333344445555",
        "text": "Staff Machine Learning Engineer",
        "categories": {"location": "San Francisco, CA", "team": "ML", "commitment": "Full-time"},
        "workplaceType": "hybrid",
        "createdAt": 1764000000000,
        "descriptionPlain": "Train and ship ranking models with PyTorch.",
        "lists": [{"text": "Requirements", "content": "<li>Python</li><li>AWS</li>"}],
        "additionalPlain": "We offer equity.",
        "salaryRange": {"currency": "USD", "interval": "per-year-salary", "min": 220000, "max": 280000},
    },
    {
        "id": "ffff0000-1111-2222-3333-444455556666",
        "text": "Data Analyst",
        "categories": {"location": "Remote"},
        "workplaceType": "remote",
        "createdAt": 1764100000000,
        "descriptionPlain": "SQL and Tableau dashboards.",
        "salaryRange": {"currency": "EUR", "interval": "per-year-salary", "min": 50000, "max": 60000},
    },
]


def _client(routes: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response
        return httpx.Response(404, json={"error": "not found"})

    return httpx.Client(transport=httpx.MockTransport(handler))


class TestHelpers:
    def test_html_to_text_double_unescape(self):
        text = html_to_text(GREENHOUSE_PAYLOAD["jobs"][0]["content"])
        assert "<" not in text
        assert "Build APIs in Python and PostgreSQL." in text
        assert "Docker & Kubernetes" in text

    @pytest.mark.parametrize("title,expected", [
        ("Senior Backend Engineer", "senior"),
        ("Sr. Data Engineer", "senior"),
        ("Staff Software Engineer", "staff"),
        ("Principal Engineer", "staff"),
        ("Software Engineering Intern", "junior"),
        ("New Grad Software Engineer", "junior"),
        ("Backend Engineer", "mid"),
    ])
    def test_infer_seniority(self, title, expected):
        assert infer_seniority(title) == expected


class TestGreenhouseSource:
    def test_parses_postings(self):
        client = _client({"https://boards-api.greenhouse.io/v1/boards/acme/jobs":
                          httpx.Response(200, json=GREENHOUSE_PAYLOAD)})
        postings = GreenhouseSource(boards=["acme"], client=client).fetch(10)

        assert len(postings) == 2  # empty-title job skipped
        first, intern = postings
        assert first.external_id == "acme:4012345"
        assert first.company == "Acme"
        assert first.remote is True
        assert first.seniority == "senior"
        assert "PostgreSQL" in first.description
        assert first.posted_at.year == 2026
        assert intern.company == "acme"  # falls back to the board token
        assert intern.seniority == "junior"
        assert intern.remote is False

    def test_respects_count_across_boards(self):
        client = _client({
            "https://boards-api.greenhouse.io/v1/boards/a/jobs": httpx.Response(200, json=GREENHOUSE_PAYLOAD),
            "https://boards-api.greenhouse.io/v1/boards/b/jobs": httpx.Response(200, json=GREENHOUSE_PAYLOAD),
        })
        postings = GreenhouseSource(boards=["a", "b"], client=client).fetch(3)
        assert [p.external_id for p in postings] == ["a:4012345", "a:4012346", "b:4012345"]

    def test_bad_board_is_skipped(self):
        client = _client({"https://boards-api.greenhouse.io/v1/boards/good/jobs":
                          httpx.Response(200, json=GREENHOUSE_PAYLOAD)})
        postings = GreenhouseSource(boards=["renamed-co", "good"], client=client).fetch(10)
        assert len(postings) == 2

    def test_all_boards_failing_raises(self):
        client = _client({})
        with pytest.raises(httpx.HTTPStatusError):
            GreenhouseSource(boards=["gone"], client=client).fetch(10)

    def test_no_boards_configured(self):
        with pytest.raises(ValueError):
            GreenhouseSource(boards=[]).fetch(1)


class TestLeverSource:
    def test_parses_postings(self):
        client = _client({"https://api.lever.co/v0/postings/acme": httpx.Response(200, json=LEVER_PAYLOAD)})
        ml, analyst = LeverSource(boards=["acme"], client=client).fetch(10)

        assert ml.external_id == "acme:a1b2c3d4-0000-1111-2222-333344445555"
        assert ml.seniority == "staff"
        assert ml.remote is False
        assert (ml.salary_min, ml.salary_max) == (220000, 280000)
        assert "PyTorch" in ml.description and "AWS" in ml.description and "equity" in ml.description
        assert analyst.remote is True
        assert analyst.salary_min is None  # non-USD salary ignored


class TestRegistry:
    def test_get_source_knows_job_boards(self):
        assert isinstance(get_source("greenhouse"), GreenhouseSource)
        assert isinstance(get_source("lever"), LeverSource)


class TestPipelineWithGreenhouse:
    def test_scrape_source_ingests_real_board_shape(self, monkeypatch):
        """Full Celery task (eager mode) with the Greenhouse source mocked at the HTTP layer."""
        from backend.common.database import SessionLocal
        from backend.common.models import Job
        from backend.scraper import job_boards
        from backend.scraper.tasks import scrape_source

        client = _client({"https://boards-api.greenhouse.io/v1/boards/acme/jobs":
                          httpx.Response(200, json=GREENHOUSE_PAYLOAD)})
        real_init = job_boards.GreenhouseSource.__init__

        def init(self, seed=None, boards=None, client_=None):
            real_init(self, seed=seed, boards=["acme"], client=client)

        monkeypatch.setattr(job_boards.GreenhouseSource, "__init__", init)

        result = scrape_source.apply(args=("greenhouse", 10)).get()
        assert result["new"] == 2
        assert scrape_source.apply(args=("greenhouse", 10)).get()["new"] == 0  # dedup

        with SessionLocal() as db:
            job = db.query(Job).filter_by(external_id="acme:4012345").one()
            assert job.source == "greenhouse"
            assert job.embedded is True
            assert "python" in job.skills and "postgresql" in job.skills
