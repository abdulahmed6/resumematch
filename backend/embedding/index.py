"""FAISS vector index wrapper.

Uses IndexFlatIP wrapped in IndexIDMap2 so vectors are addressed by job id.
Since all vectors are L2-normalised, inner product == cosine similarity.
Thread-safe via a coarse lock (FAISS flat indexes are fast enough that this
is not a bottleneck at this scale — 40ms-class queries over tens of
thousands of vectors).
"""
import os
import threading

import faiss
import numpy as np

from backend.common.config import get_settings


class VectorIndex:
    def __init__(self, dim: int, path: str | None = None):
        self.dim = dim
        self.path = path
        self._lock = threading.Lock()
        self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))

    # -- persistence ---------------------------------------------------------
    def save(self) -> None:
        if not self.path:
            return
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            faiss.write_index(self._index, self.path)

    def load(self) -> bool:
        if not self.path or not os.path.exists(self.path):
            return False
        with self._lock:
            index = faiss.read_index(self.path)
            if index.d != self.dim:
                return False
            self._index = index
        return True

    # -- operations -----------------------------------------------------------
    @property
    def size(self) -> int:
        return int(self._index.ntotal)

    def add(self, ids: list[int], vectors: np.ndarray) -> None:
        if len(ids) == 0:
            return
        if vectors.shape != (len(ids), self.dim):
            raise ValueError(f"expected shape ({len(ids)}, {self.dim}), got {vectors.shape}")
        id_arr = np.asarray(ids, dtype=np.int64)
        with self._lock:
            # remove_ids first so re-adding the same job id is an upsert
            self._index.remove_ids(id_arr)
            self._index.add_with_ids(vectors.astype(np.float32), id_arr)

    def remove(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._index.remove_ids(np.asarray(ids, dtype=np.int64))

    def search(self, vector: np.ndarray, top_k: int = 10) -> list[tuple[int, float]]:
        """Return [(job_id, score)] sorted by descending similarity."""
        if self.size == 0:
            return []
        q = vector.reshape(1, -1).astype(np.float32)
        with self._lock:
            scores, ids = self._index.search(q, min(top_k, self.size))
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

    def reset(self) -> None:
        with self._lock:
            self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))


_index: VectorIndex | None = None


def get_index() -> VectorIndex:
    """Singleton index; attempts to load persisted index on first use."""
    global _index
    if _index is None:
        settings = get_settings()
        _index = VectorIndex(dim=settings.embedding_dim, path=settings.faiss_index_path)
        _index.load()
    return _index
