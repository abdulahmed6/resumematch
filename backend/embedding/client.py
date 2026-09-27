"""Client used by gateway/scraper to reach the embedding service.

Two modes:
- HTTP mode (RM_EMBEDDING_URL set): true microservice call, used in
  docker-compose deployments.
- In-process mode (default in dev/tests): calls the embedder/index directly,
  so the whole stack runs in a single process without extra infrastructure.
"""
import time

import httpx
import numpy as np

from backend.common.config import get_settings


class EmbeddingClient:
    def __init__(self, base_url: str | None = None):
        settings = get_settings()
        self.base_url = (base_url if base_url is not None else settings.embedding_url).rstrip("/")

    # ------------------------------------------------------------------
    def _local(self):
        from backend.embedding.embedder import get_embedder
        from backend.embedding.index import get_index

        return get_embedder(), get_index()

    # ------------------------------------------------------------------
    def index_add(self, ids: list[int], texts: list[str]) -> int:
        if self.base_url:
            resp = httpx.post(f"{self.base_url}/index/add",
                              json={"ids": ids, "texts": texts}, timeout=120)
            resp.raise_for_status()
            return resp.json().get("added", 0)
        embedder, index = self._local()
        vecs = embedder.encode(texts)
        index.add(ids, vecs)
        index.save()
        return len(ids)

    def search(self, query: str, top_k: int = 10) -> dict:
        if self.base_url:
            resp = httpx.post(f"{self.base_url}/index/search",
                              json={"query": query, "top_k": top_k}, timeout=30)
            resp.raise_for_status()
            return resp.json()
        embedder, index = self._local()
        started = time.perf_counter()
        qvec = embedder.encode([query])[0]
        hits = index.search(np.asarray(qvec), top_k=top_k)
        latency_ms = (time.perf_counter() - started) * 1000
        return {
            "hits": [{"id": job_id, "score": score} for job_id, score in hits],
            "latency_ms": round(latency_ms, 3),
            "index_size": index.size,
        }

    def index_size(self) -> int:
        if self.base_url:
            resp = httpx.get(f"{self.base_url}/healthz", timeout=10)
            resp.raise_for_status()
            return resp.json().get("index_size", 0)
        _, index = self._local()
        return index.size


_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
