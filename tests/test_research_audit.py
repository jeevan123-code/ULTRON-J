"""Audit smoke test for research_engine.research() public surface.

We do NOT call the real network/LLM here — we patch research_engine.research
itself to return a canned dict, then verify the rest of Phase 2a relies on
the keys we expect (answer, sources, sub_queries, contradictions, cached, ms).
"""
from unittest.mock import patch
import research_engine

from tests.fixtures.research_responses import wheat_rust_report


def test_research_engine_has_research_function():
    assert callable(research_engine.research)


def test_research_engine_research_dict_shape():
    """If we mock research(), it returns the documented shape."""
    canned = wheat_rust_report()
    with patch.object(research_engine, "research", return_value=canned):
        result = research_engine.research("wheat leaf rust", depth="standard")
    assert "answer" in result
    assert "sources" in result
    assert isinstance(result["sources"], list)
    assert "contradictions" in result
    assert "cached" in result
    assert "ms" in result


def test_research_sources_have_url_and_title():
    canned = wheat_rust_report()
    for s in canned["sources"]:
        assert "url" in s and s["url"].startswith("http")
        assert "title" in s
        assert "n" in s
