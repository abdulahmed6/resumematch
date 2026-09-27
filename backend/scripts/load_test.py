"""Load-test the gateway's /api/search endpoint against a locally-seeded index.

This is a small asyncio + httpx load generator, not a replacement for a real
tool like locust/k6 (neither of which could be installed in this environment
-- no package-manager access beyond pip/npm). It's intentionally simple:
spin up the gateway (dev mode: sqlite + in-process embedder + eager Celery)
against a fresh throwaway database and FAISS index, seed it with real
synthetic postings through the actual `scrape_source` pipeline, then fire
concurrent search requests at it and report the REAL measured throughput and
latency distribution.

Usage:
    python -m backend.scripts.load_test [--jobs 5200] [--concurrency 50] [--requests 2000]

Numbers this script prints are real measurements from this run, on whatever
hardware it happens to execute on -- they are not a substitute for testing
against the actual deployed multi-worker/Postgres/Redis stack, which this
sandbox cannot run (no Docker). See the printed caveats at the end of the
report.
"""
import argparse
import asyncio
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

QUERIES = [
    "python backend engineer with fastapi and postgres experience",
    "senior machine learning engineer pytorch distributed training",
    "remote frontend react typescript developer",
    "devops engineer kubernetes terraform aws ci/cd",
    "data scientist sql pandas machine learning",
    "site reliability engineer monitoring distributed systems",
    "full stack engineer node.js react postgresql",
    "platform engineer golang grpc kafka",
    "nlp engineer llms embeddings pytorch",
    "security engineer aws linux monitoring",
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_healthz(base_url: str, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last_exc = None
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base_url}/api/healthz", timeout=2, trust_env=False)
            if resp.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_exc = exc
        time.sleep(0.25)
    raise RuntimeError(f"gateway never became healthy at {base_url}: {last_exc}")


def _seed(job_count: int, batches: int) -> dict:
    """Populate the (already-env-configured) DB + FAISS index in-process."""
    from backend.common.database import init_db
    from backend.scripts.seed import seed

    init_db()
    return seed(count=job_count, batches=batches)


async def _fire_requests(base_url: str, total_requests: int, concurrency: int) -> dict:
    latencies_client_ms: list[float] = []
    latencies_server_ms: list[float] = []
    errors = 0
    statuses: dict[int, int] = {}

    sem = asyncio.Semaphore(concurrency)

    async def one(client: httpx.AsyncClient, i: int) -> None:
        nonlocal errors
        query = QUERIES[i % len(QUERIES)]
        payload = {"query": query, "top_k": 10}
        started = time.perf_counter()
        async with sem:
            try:
                resp = await client.post(f"{base_url}/api/search", json=payload, timeout=30)
            except httpx.HTTPError:
                errors += 1
                return
        elapsed_ms = (time.perf_counter() - started) * 1000
        statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1
        if resp.status_code != 200:
            errors += 1
            return
        latencies_client_ms.append(elapsed_ms)
        data = resp.json()
        if "latency_ms" in data:
            latencies_server_ms.append(data["latency_ms"])

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits, trust_env=False) as client:
        started = time.perf_counter()
        await asyncio.gather(*(one(client, i) for i in range(total_requests)))
        wall_s = time.perf_counter() - started

    def pct(data: list[float], p: float) -> float | None:
        if not data:
            return None
        data = sorted(data)
        idx = min(len(data) - 1, int(len(data) * p))
        return round(data[idx], 3)

    return {
        "total_requests": total_requests,
        "concurrency": concurrency,
        "errors": errors,
        "statuses": statuses,
        "wall_seconds": round(wall_s, 3),
        "throughput_req_per_s": round((total_requests - errors) / wall_s, 2) if wall_s > 0 else None,
        "client_latency_ms": {
            "mean": round(statistics.mean(latencies_client_ms), 3) if latencies_client_ms else None,
            "p50": pct(latencies_client_ms, 0.50),
            "p95": pct(latencies_client_ms, 0.95),
            "p99": pct(latencies_client_ms, 0.99),
            "max": round(max(latencies_client_ms), 3) if latencies_client_ms else None,
        },
        "server_reported_search_latency_ms": {
            "mean": round(statistics.mean(latencies_server_ms), 3) if latencies_server_ms else None,
            "p50": pct(latencies_server_ms, 0.50),
            "p95": pct(latencies_server_ms, 0.95),
            "p99": pct(latencies_server_ms, 0.99),
            "max": round(max(latencies_server_ms), 3) if latencies_server_ms else None,
        },
    }


def run(job_count: int, batches: int, concurrency: int, total_requests: int,
        workers: int = 1) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="rm_loadtest_"))
    db_path = tmp / "loadtest.db"
    index_path = tmp / "loadtest_faiss.index"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["RM_DATABASE_URL"] = f"sqlite:///{db_path}"
    env["RM_CELERY_EAGER"] = "true"
    env["RM_EMBEDDING_URL"] = ""
    env["RM_FAISS_INDEX_PATH"] = str(index_path)

    # Seed in-process first (same env vars, so it writes to the same sqlite
    # file + FAISS index file the server subprocess will read on startup).
    for k, v in env.items():
        os.environ[k] = v
    print(f"Seeding {job_count} synthetic postings across {batches} batches "
          f"through the real scrape_source -> index_jobs pipeline...")
    seed_summary = _seed(job_count, batches)
    print(f"Seed done: {seed_summary}")

    print(f"Starting gateway subprocess on {base_url} (workers={workers}) ...")
    cmd = [sys.executable, "-m", "uvicorn", "backend.gateway.main:app",
           "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"]
    if workers > 1:
        cmd += ["--workers", str(workers)]
    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    try:
        _wait_for_healthz(base_url)
        stats = httpx.get(f"{base_url}/api/stats", timeout=10, trust_env=False).json()
        print(f"Gateway up. /api/stats before load: {stats}")

        print(f"Firing {total_requests} requests at /api/search "
              f"(concurrency={concurrency})...")
        result = asyncio.run(_fire_requests(base_url, total_requests, concurrency))

        stats_after = httpx.get(f"{base_url}/api/stats", timeout=10, trust_env=False).json()
        result["seed_summary"] = seed_summary
        result["total_indexed_jobs"] = stats_after.get("total_indexed")
        result["gateway_avg_query_latency_ms"] = stats_after.get("avg_query_latency_ms")
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=5200,
                         help="number of synthetic job postings to seed before the load test")
    parser.add_argument("--batches", type=int, default=15)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=1,
                         help="number of uvicorn worker processes for the gateway subprocess")
    args = parser.parse_args()

    result = run(args.jobs, args.batches, args.concurrency, args.requests, args.workers)

    print("\n" + "=" * 72)
    print("LOAD TEST RESULT (real measurement from this run, this machine)")
    print("=" * 72)
    print(json.dumps(result, indent=2))
    print("=" * 72)
    print(
        "Caveats: single process, single SQLite file, in-process hashing\n"
        "embedder, Celery in eager (in-process) mode -- NOT the distributed\n"
        "docker-compose stack (3 Celery workers + Postgres + Redis + real\n"
        "sentence-transformers embedder). Numbers here characterize the\n"
        "FAISS search path and FastAPI request handling on this sandbox's\n"
        "CPU; they will differ (likely improve, given the real stack's\n"
        "worker parallelism) on the deployed multi-node setup, and haven't\n"
        "been measured there. Don't quote these figures as production\n"
        "numbers without re-running this same script against that stack."
    )
