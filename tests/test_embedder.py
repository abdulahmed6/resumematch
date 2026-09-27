"""Tests for the HashingEmbedder."""
import numpy as np
import pytest

from backend.embedding.embedder import HashingEmbedder, get_embedder


class TestHashingEmbedder:
    """Test determinism, shape, normalization, and similarity scoring."""

    def test_determinism_same_seed(self):
        """Same input should always produce identical vectors."""
        embedder = HashingEmbedder(dim=384)
        text = "Python and FastAPI"

        vec1 = embedder.encode([text])[0]
        vec2 = embedder.encode([text])[0]

        np.testing.assert_array_equal(vec1, vec2)

    def test_output_shape(self):
        """Output shape should be (n_texts, dim)."""
        embedder = HashingEmbedder(dim=384)

        result = embedder.encode(["text1", "text2", "text3"])
        assert result.shape == (3, 384)
        assert result.dtype == np.float32

    def test_empty_text_list(self):
        """Empty list should return (0, dim) array."""
        embedder = HashingEmbedder(dim=384)
        result = embedder.encode([])
        assert result.shape == (0, 384)
        assert result.dtype == np.float32

    def test_single_text(self):
        """Single text should work correctly."""
        embedder = HashingEmbedder(dim=384)
        result = embedder.encode(["Python FastAPI"])
        assert result.shape == (1, 384)

    def test_empty_text_produces_zero_vector(self):
        """Empty text should produce zero vector."""
        embedder = HashingEmbedder(dim=384)
        result = embedder.encode([""])
        vec = result[0]
        # Zero vector
        np.testing.assert_array_almost_equal(vec, np.zeros(384, dtype=np.float32))

    def test_l2_normalization(self):
        """All vectors should be L2-normalized (norm ~1.0)."""
        embedder = HashingEmbedder(dim=384)
        texts = [
            "Python",
            "JavaScript and React",
            "Docker Kubernetes AWS",
            "Machine Learning Deep Learning",
        ]
        vecs = embedder.encode(texts)

        for i, vec in enumerate(vecs):
            if texts[i]:  # Non-empty text
                norm = np.linalg.norm(vec)
                assert np.isclose(norm, 1.0, atol=1e-5), f"Vector {i} has norm {norm}"

    def test_similar_texts_higher_score(self):
        """Similar texts should have higher cosine similarity."""
        embedder = HashingEmbedder(dim=384)

        # Very similar texts
        vec1 = embedder.encode(["Python and FastAPI"])[0]
        vec2 = embedder.encode(["Python and FastAPI"])[0]
        score_identical = np.dot(vec1, vec2)

        # Different texts
        vec3 = embedder.encode(["Java and Spring"])[0]
        score_different = np.dot(vec1, vec3)

        # Identical texts should have higher similarity than different ones
        assert score_identical > score_different
        assert np.isclose(score_identical, 1.0, atol=1e-5)

    def test_no_encoding_special_chars(self):
        """Text with special chars (outside word boundaries) should be handled."""
        embedder = HashingEmbedder(dim=384)
        # Special chars should be skipped
        result = embedder.encode(["@#$%^"])
        vec = result[0]
        # Should be near zero (no valid tokens)
        norm = np.linalg.norm(vec)
        assert norm < 0.1

    def test_embedding_dimension_configurable(self):
        """Dimension should be configurable."""
        for dim in [128, 256, 384, 512]:
            embedder = HashingEmbedder(dim=dim)
            result = embedder.encode(["test"])
            assert result.shape == (1, dim)

    def test_get_embedder_singleton(self):
        """get_embedder should return a singleton."""
        embedder1 = get_embedder()
        embedder2 = get_embedder()
        assert embedder1 is embedder2
