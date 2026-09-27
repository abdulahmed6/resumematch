"""Tests for job posting sources."""
import pytest

from backend.scraper.sources import SyntheticSource, get_source


class TestSyntheticSource:
    """Test determinism, count, and posting field validity."""

    def test_determinism_same_seed(self):
        """Same seed should always produce identical postings."""
        source1 = SyntheticSource(seed=42)
        postings1 = source1.fetch(10)

        source2 = SyntheticSource(seed=42)
        postings2 = source2.fetch(10)

        assert len(postings1) == len(postings2)
        for p1, p2 in zip(postings1, postings2):
            assert p1.external_id == p2.external_id
            assert p1.title == p2.title
            assert p1.company == p2.company
            assert p1.salary_min == p2.salary_min
            assert p1.salary_max == p2.salary_max

    def test_different_seeds_different_postings(self):
        """Different seeds should produce different postings."""
        source1 = SyntheticSource(seed=42)
        postings1 = source1.fetch(10)

        source2 = SyntheticSource(seed=43)
        postings2 = source2.fetch(10)

        # At least some should be different
        external_ids1 = {p.external_id for p in postings1}
        external_ids2 = {p.external_id for p in postings2}
        assert external_ids1 != external_ids2

    def test_fetch_count(self):
        """Fetch should return requested count."""
        source = SyntheticSource(seed=42)
        for count in [1, 5, 10, 100]:
            postings = source.fetch(count)
            assert len(postings) == count

    def test_salary_min_less_than_max(self):
        """salary_min should always be less than salary_max."""
        source = SyntheticSource(seed=42)
        postings = source.fetch(100)

        for p in postings:
            assert p.salary_min < p.salary_max

    def test_external_id_unique_ish(self):
        """External IDs should be mostly unique (deterministic per seed)."""
        source = SyntheticSource(seed=42)
        postings = source.fetch(100)

        external_ids = [p.external_id for p in postings]
        unique_ids = set(external_ids)
        # Most should be unique (allow some collisions due to random hash)
        assert len(unique_ids) > 90

    def test_posting_fields_valid(self):
        """All posting fields should be valid and non-empty."""
        source = SyntheticSource(seed=42)
        postings = source.fetch(10)

        for p in postings:
            assert p.external_id and isinstance(p.external_id, str)
            assert p.title and isinstance(p.title, str)
            assert p.company and isinstance(p.company, str)
            assert p.location and isinstance(p.location, str)
            assert isinstance(p.remote, bool)
            assert p.seniority in ("junior", "mid", "senior", "staff")
            assert isinstance(p.salary_min, float)
            assert isinstance(p.salary_max, float)
            assert p.description and isinstance(p.description, str)
            assert isinstance(p.skills, list)
            assert all(isinstance(s, str) for s in p.skills)
            assert p.posted_at is not None

    def test_skills_in_taxonomy(self):
        """All extracted skills should be in the taxonomy."""
        from backend.common.skills import SKILL_TAXONOMY
        source = SyntheticSource(seed=42)
        postings = source.fetch(20)

        all_skills = set()
        for p in postings:
            all_skills.update(p.skills)

        for skill in all_skills:
            assert skill in SKILL_TAXONOMY, f"Skill {skill} not in taxonomy"

    def test_source_name(self):
        """Source name should be 'synthetic'."""
        source = SyntheticSource()
        assert source.name == "synthetic"

    def test_get_source_synthetic(self):
        """get_source should return SyntheticSource for 'synthetic'."""
        source = get_source("synthetic", seed=42)
        assert isinstance(source, SyntheticSource)
        postings = source.fetch(5)
        assert len(postings) == 5

    def test_get_source_invalid(self):
        """get_source should raise ValueError for unknown source."""
        with pytest.raises(ValueError, match="unknown source"):
            get_source("invalid_source")

    def test_no_seed_random(self):
        """No seed should produce different results each time."""
        source1 = SyntheticSource()
        postings1 = source1.fetch(10)

        source2 = SyntheticSource()
        postings2 = source2.fetch(10)

        external_ids1 = {p.external_id for p in postings1}
        external_ids2 = {p.external_id for p in postings2}
        # Should be different (with very high probability)
        assert external_ids1 != external_ids2
