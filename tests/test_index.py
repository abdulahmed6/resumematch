"""Tests for the FAISS vector index."""
import numpy as np
import pytest
import tempfile
import os

from backend.embedding.index import VectorIndex, get_index


class TestVectorIndex:
    """Test add, search, upsert, remove, and persistence."""

    def test_add_vectors(self):
        """Add vectors to the index."""
        index = VectorIndex(dim=384, path=None)
        ids = [1, 2, 3]
        vecs = np.random.randn(3, 384).astype(np.float32)
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)  # normalize

        index.add(ids, vecs)
        assert index.size == 3

    def test_add_empty_list(self):
        """Adding empty list should be a no-op."""
        index = VectorIndex(dim=384, path=None)
        index.add([], np.zeros((0, 384), dtype=np.float32))
        assert index.size == 0

    def test_add_shape_validation(self):
        """Should validate vector shape matches dimension."""
        index = VectorIndex(dim=384, path=None)
        vecs = np.random.randn(2, 256).astype(np.float32)  # wrong shape
        with pytest.raises(ValueError, match="expected shape"):
            index.add([1, 2], vecs)

    def test_search_empty_index(self):
        """Searching empty index should return empty list."""
        index = VectorIndex(dim=384, path=None)
        query_vec = np.random.randn(384).astype(np.float32)
        query_vec = query_vec / np.linalg.norm(query_vec)
        results = index.search(query_vec, top_k=10)
        assert results == []

    def test_search_returns_top_k(self):
        """Search should return top-k results."""
        index = VectorIndex(dim=384, path=None)
        ids = list(range(1, 21))
        vecs = np.random.randn(20, 384).astype(np.float32)
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

        index.add(ids, vecs)

        query_vec = np.random.randn(384).astype(np.float32)
        query_vec = query_vec / np.linalg.norm(query_vec)
        results = index.search(query_vec, top_k=5)

        assert len(results) == 5
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)
        assert all(isinstance(r[0], int) and isinstance(r[1], float) for r in results)

    def test_search_returns_scores(self):
        """Search should return scores in descending order."""
        index = VectorIndex(dim=384, path=None)
        ids = [1, 2, 3, 4, 5]
        vecs = np.eye(384, dtype=np.float32)[:5]  # orthogonal vectors
        index.add(ids, vecs)

        # Query with the first vector
        query_vec = vecs[0].copy()
        results = index.search(query_vec, top_k=5)

        # Scores should be in descending order
        scores = [r[1] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_upsert_same_id(self):
        """Adding same id should replace (upsert behavior)."""
        index = VectorIndex(dim=384, path=None)

        # Add vector
        vec1 = np.random.randn(384).astype(np.float32)
        vec1 = vec1 / np.linalg.norm(vec1)
        index.add([1], vec1.reshape(1, -1))
        assert index.size == 1

        # Add different vector with same id
        vec2 = np.random.randn(384).astype(np.float32)
        vec2 = vec2 / np.linalg.norm(vec2)
        index.add([1], vec2.reshape(1, -1))
        # Size should still be 1
        assert index.size == 1

        # Search should return the new vector
        results = index.search(vec2, top_k=1)
        assert results[0][0] == 1

    def test_remove_ids(self):
        """Remove should delete vectors by id."""
        index = VectorIndex(dim=384, path=None)
        ids = [1, 2, 3, 4, 5]
        vecs = np.random.randn(5, 384).astype(np.float32)
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

        index.add(ids, vecs)
        assert index.size == 5

        index.remove([2, 4])
        assert index.size == 3

    def test_remove_empty_list(self):
        """Removing empty list should be a no-op."""
        index = VectorIndex(dim=384, path=None)
        ids = [1, 2, 3]
        vecs = np.random.randn(3, 384).astype(np.float32)
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        index.add(ids, vecs)
        assert index.size == 3

        index.remove([])
        assert index.size == 3

    def test_reset(self):
        """Reset should clear the index."""
        index = VectorIndex(dim=384, path=None)
        ids = [1, 2, 3]
        vecs = np.random.randn(3, 384).astype(np.float32)
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

        index.add(ids, vecs)
        assert index.size == 3

        index.reset()
        assert index.size == 0

    def test_save_load_roundtrip(self):
        """Save and load should preserve the index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.index")

            # Create and populate index
            index1 = VectorIndex(dim=384, path=path)
            ids = [1, 2, 3, 4, 5]
            vecs = np.random.randn(5, 384).astype(np.float32)
            vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
            index1.add(ids, vecs)
            assert index1.size == 5

            # Save
            index1.save()
            assert os.path.exists(path)

            # Load into new index
            index2 = VectorIndex(dim=384, path=path)
            assert index2.size == 0  # Not loaded yet
            loaded = index2.load()
            assert loaded is True
            assert index2.size == 5

            # Search should work on loaded index
            query_vec = vecs[0].copy()
            results = index2.search(query_vec, top_k=1)
            assert len(results) == 1

    def test_load_nonexistent_file(self):
        """Load should return False for nonexistent file."""
        index = VectorIndex(dim=384, path="/nonexistent/path/to/file.index")
        result = index.load()
        assert result is False
        assert index.size == 0

    def test_load_wrong_dimension(self):
        """Load should return False if dimension doesn't match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.index")

            # Save index with dim=384
            index1 = VectorIndex(dim=384, path=path)
            vecs = np.random.randn(2, 384).astype(np.float32)
            vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
            index1.add([1, 2], vecs)
            index1.save()

            # Try to load with dim=256
            index2 = VectorIndex(dim=256, path=path)
            result = index2.load()
            assert result is False

    def test_get_index_singleton(self):
        """get_index should return a singleton."""
        index1 = get_index()
        index2 = get_index()
        assert index1 is index2
