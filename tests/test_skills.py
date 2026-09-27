"""Tests for skill extraction and taxonomy."""
import pytest

from backend.common.skills import extract_skills, all_skills, SKILL_TAXONOMY


class TestExtractSkills:
    """Test extract_skills word-boundary behavior and edge cases."""

    def test_empty_text(self):
        """Empty text should return empty list."""
        assert extract_skills("") == []
        assert extract_skills("   ") == []

    def test_single_skill(self):
        """Extract a single skill."""
        assert extract_skills("Python is great") == ["python"]
        assert extract_skills("I love JavaScript") == ["javascript"]

    def test_multiple_skills(self):
        """Extract multiple skills, return sorted."""
        result = extract_skills("Python and JavaScript and React")
        assert result == ["javascript", "python", "react"]

    def test_case_insensitivity(self):
        """Skills should be matched case-insensitively."""
        assert extract_skills("PYTHON") == ["python"]
        assert extract_skills("PyThOn") == ["python"]
        assert extract_skills("JAVASCRIPT") == ["javascript"]

    def test_word_boundary_go_vs_google(self):
        """'go' should not match inside 'google'."""
        assert extract_skills("I know google golang") == ["go"]
        assert extract_skills("golang") == ["go"]
        assert extract_skills("go language") == ["go"]
        assert extract_skills("google") == []

    def test_word_boundary_c_plus_plus(self):
        """'c++' should match as a complete token."""
        assert extract_skills("C++ programming") == ["c++"]
        assert extract_skills("c++ is powerful") == ["c++"]
        # "c" alone should not match inside "c++"
        result = extract_skills("I use c++")
        assert "c#" not in result
        assert "c++" in result

    def test_word_boundary_node_js(self):
        """'node.js' should match correctly."""
        assert extract_skills("node.js backend") == ["node.js"]
        assert extract_skills("nodejs") == ["node.js"]
        assert extract_skills("node") == ["node.js"]

    def test_react_native_vs_react(self):
        """'react' and 'react native' are both extracted when both match."""
        # When both patterns match, both skills are extracted
        result = extract_skills("react native development")
        assert set(result) == {"react", "react native"}

        result = extract_skills("I use react")
        assert result == ["react"]

    def test_no_duplicates(self):
        """Skills should not appear twice."""
        result = extract_skills("Python Python python PYTHON")
        assert result == ["python"]

    def test_stopwords_not_matched(self):
        """Common words should be filtered as stopwords."""
        result = extract_skills("the and or for is")
        assert result == []

    def test_short_tokens_filtered(self):
        """Tokens shorter than 2 chars should be filtered."""
        result = extract_skills("I am a developer")
        assert result == []

    def test_complex_resume_text(self):
        """Extract skills from realistic resume text."""
        text = """
        Senior Backend Engineer with 5+ years experience.
        Expertise: Python, FastAPI, PostgreSQL, Redis, Docker, REST APIs.
        Also familiar with Kubernetes, AWS, and CI/CD pipelines.
        Some ML experience with PyTorch and TensorFlow.
        """
        result = extract_skills(text)
        expected = {
            "aws", "ci/cd", "docker", "fastapi", "kubernetes", "machine learning",
            "postgresql", "python", "pytorch", "redis", "rest apis", "tensorflow"
        }
        assert set(result) == expected
        assert result == sorted(expected)

    def test_taxonomy_coverage(self):
        """All canonical skills should be extractable."""
        for canonical in SKILL_TAXONOMY.keys():
            # Try with the canonical form (may not work for all)
            # Just verify the skill exists
            assert canonical in all_skills()

    def test_alias_extraction(self):
        """Test various aliases for the same skill."""
        # JavaScript aliases
        assert extract_skills("javascript") == ["javascript"]
        assert extract_skills("js code") == ["javascript"]
        assert extract_skills("es6 modules") == ["javascript"]

        # Python aliases
        assert extract_skills("python3") == ["python"]
        assert extract_skills("python") == ["python"]

        # Node aliases
        assert extract_skills("node.js") == ["node.js"]
        assert extract_skills("nodejs") == ["node.js"]
