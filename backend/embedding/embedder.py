"""Text embedding backends.

Default backend is a fast, dependency-light *hashing embedder*: unigrams and
bigrams are hashed into a fixed number of signed buckets (feature hashing),
TF-weighted and L2-normalised. This gives useful lexical-semantic similarity
with zero model downloads, which keeps the pipeline runnable anywhere.

A `sentence-transformers` backend (all-MiniLM-L6-v2) can be enabled with
RM_EMBEDDER_BACKEND=sentence-transformers for true semantic embeddings; it
exposes the exact same interface so nothing else changes.
"""
import hashlib
import re
from abc import ABC, abstractmethod

import numpy as np

from backend.common.config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or that the to was were will with we you our".split()
)


def _tokenize(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


class BaseEmbedder(ABC):
    dim: int

    @abstractmethod
    def encode(self, texts: list[str]) -> np.ndarray:
        """Return float32 array of shape (len(texts), dim), L2-normalised."""


class HashingEmbedder(BaseEmbedder):
    """Signed feature-hashing of unigrams + bigrams, L2-normalised."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.md5(feature.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % self.dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        return idx, sign

    def _encode_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = _tokenize(text)
        if not tokens:
            return vec
        features = list(tokens)
        features.extend(f"{a}_{b}" for a, b in zip(tokens, tokens[1:]))
        for feat in features:
            idx, sign = self._bucket(feat)
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._encode_one(t) for t in texts])


class SentenceTransformerEmbedder(BaseEmbedder):
    """Real semantic embeddings via sentence-transformers (optional heavy dep)."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # lazy import

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)


_embedder: BaseEmbedder | None = None


def get_embedder() -> BaseEmbedder:
    """Singleton embedder chosen by settings."""
    global _embedder
    if _embedder is None:
        settings = get_settings()
        if settings.embedder_backend == "sentence-transformers":
            _embedder = SentenceTransformerEmbedder()
        else:
            _embedder = HashingEmbedder(dim=settings.embedding_dim)
    return _embedder
