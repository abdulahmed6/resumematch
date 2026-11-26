"""Real job-board sources: Greenhouse and Lever public posting APIs.

Both boards publish a company's open roles as JSON so that companies can show
them on their own careers pages. No API key or HTML scraping is needed:

    Greenhouse: GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
    Lever:      GET https://api.lever.co/v0/postings/{company}?mode=json

Each source implements the same ``fetch(count) -> list[Posting]`` interface as
``SyntheticSource``, so the Celery pipeline (dedup, skill extraction, Postgres,
embedding, FAISS) is unchanged. Which companies to pull from is configured
with ``RM_GREENHOUSE_BOARDS`` and ``RM_LEVER_COMPANIES`` (comma-separated board
tokens, the part after ``boards.greenhouse.io/`` or ``jobs.lever.co/`` in a
company's careers URL).

Error handling: a board that fails (renamed company, 404, timeout) is logged
and skipped so one bad token doesn't sink the batch. If *every* board fails,
the error propagates, and ``scrape_source`` retries the task three times and
then sends it to the dead-letter queue.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone

import httpx

from backend.common.config import get_settings
from backend.scraper.sources import Posting

log = logging.getLogger(__name__)

USER_AGENT = "ResumeMatch/1.0 (job-matching demo; +https://github.com/abdulahmed6/resumematch)"
TIMEOUT_S = 15.0

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)

# Checked in order, so "senior staff" maps to staff and "junior" wins over the default.
_SENIORITY_RULES = [
    ("staff", re.compile(r"\b(staff|principal|distinguished|director|head of)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?|lead|manager)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr\.?|intern|internship|new grad|graduate|entry[- ]level|associate)\b", re.I)),
]


def html_to_text(raw: str) -> str:
    """Strip tags from a job description. Greenhouse double-escapes its HTML."""
    text = html.unescape(html.unescape(raw or ""))
    text = re.sub(r"<\s*(br|/p|/li|/h\d)\s*/?>", "\n", text, flags=re.I)
    text = _TAG_RE.sub(" ", text)
    lines = (_WS_RE.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def infer_seniority(title: str) -> str:
    for level, pattern in _SENIORITY_RULES:
        if pattern.search(title):
            return level
    return "mid"


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


class _BoardSource:
    """Shared plumbing: iterate configured boards until ``count`` postings are collected."""

    name = "board"

    def __init__(self, seed: int | None = None, boards: list[str] | None = None,
                 client: httpx.Client | None = None):
        # `seed` is accepted for interface compatibility with SyntheticSource.
        self.boards = boards if boards is not None else self._configured_boards()
        self._client = client

    def _configured_boards(self) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _fetch_board(self, client: httpx.Client, board: str) -> list[Posting]:  # pragma: no cover
        raise NotImplementedError

    def fetch(self, count: int) -> list[Posting]:
        if not self.boards:
            raise ValueError(f"no boards configured for source '{self.name}'")
        client = self._client or httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT})
        try:
            out: list[Posting] = []
            errors: list[Exception] = []
            for board in self.boards:
                try:
                    out.extend(self._fetch_board(client, board))
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning("%s board %r failed: %s", self.name, board, exc)
                    errors.append(exc)
                    continue
                if len(out) >= count:
                    break
            if not out and errors:
                raise errors[-1]
            return out[:count]
        finally:
            if self._client is None:
                client.close()


class GreenhouseSource(_BoardSource):
    name = "greenhouse"
    URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"

    def _configured_boards(self) -> list[str]:
        return _split(get_settings().greenhouse_boards)

    def _fetch_board(self, client: httpx.Client, board: str) -> list[Posting]:
        resp = client.get(self.URL.format(board=board), params={"content": "true"})
        resp.raise_for_status()
        postings = []
        for job in resp.json().get("jobs", []):
            title = (job.get("title") or "").strip()
            if not title:
                continue
            location = ((job.get("location") or {}).get("name") or "Unspecified").strip()
            description = html_to_text(job.get("content", ""))
            postings.append(Posting(
                external_id=f"{board}:{job['id']}",
                title=title[:256],
                company=(job.get("company_name") or board).strip()[:256],
                location=location[:256],
                remote=bool(_REMOTE_RE.search(location) or _REMOTE_RE.search(title)),
                seniority=infer_seniority(title),
                salary_min=None,
                salary_max=None,
                description=description or title,
                posted_at=_parse_iso(job.get("updated_at") or job.get("first_published")),
            ))
        return postings


class LeverSource(_BoardSource):
    name = "lever"
    URL = "https://api.lever.co/v0/postings/{company}"

    def _configured_boards(self) -> list[str]:
        return _split(get_settings().lever_companies)

    def _fetch_board(self, client: httpx.Client, board: str) -> list[Posting]:
        resp = client.get(self.URL.format(company=board), params={"mode": "json"})
        resp.raise_for_status()
        postings = []
        for job in resp.json():
            title = (job.get("text") or "").strip()
            if not title:
                continue
            categories = job.get("categories") or {}
            location = (categories.get("location") or "Unspecified").strip()
            parts = [job.get("descriptionPlain") or html_to_text(job.get("description", ""))]
            for section in job.get("lists") or []:
                parts.append(section.get("text", ""))
                parts.append(html_to_text(section.get("content", "")))
            parts.append(job.get("additionalPlain") or "")
            description = "\n".join(p.strip() for p in parts if p and p.strip())
            salary_min = salary_max = None
            salary = job.get("salaryRange") or {}
            if salary.get("currency") == "USD" and salary.get("interval") == "per-year-salary":
                salary_min, salary_max = salary.get("min"), salary.get("max")
            created_ms = job.get("createdAt")
            posted_at = (datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)
                         if isinstance(created_ms, (int, float)) else datetime.now(timezone.utc))
            postings.append(Posting(
                external_id=f"{board}:{job['id']}"[:64],
                title=title[:256],
                company=board,
                location=location[:256],
                remote=(job.get("workplaceType") == "remote") or bool(_REMOTE_RE.search(location)),
                seniority=infer_seniority(title),
                salary_min=salary_min,
                salary_max=salary_max,
                description=description or title,
                posted_at=posted_at,
            ))
        return postings
