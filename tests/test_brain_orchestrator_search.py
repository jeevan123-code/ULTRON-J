"""The orchestrator's `search` task must try Tavily before the scrape chain.

brain_orchestrator was the one search caller that went straight to
local_engine.local_smart_search — whose chain is SearXNG → DuckDuckGo →
Wikipedia and contains no Tavily at all. Measured 2026-07-29: SearXNG returns
nothing (not self-hosted), DuckDuckGo answered 2 of 6 attempts, Tavily 6 of 6.

/ask, voice_routes and react_engine all try Tavily first. This brings the
orchestrator in line with them.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module            # noqa: E402
import brain_orchestrator as bo     # noqa: E402


TASK = {"kind": "search", "description": "who is al ronge"}


@pytest.fixture
def search(monkeypatch):
    """Run the orchestrator's search task against stubbed backends.

    Returns a callable taking the tavily/local stand-ins and yielding
    (task result, list of backends that were actually consulted).
    """
    def _run(tavily, local="", search_available=True):
        used = []

        def _tavily(query, *a, **k):
            used.append("tavily")
            if callable(tavily):
                return tavily(query)
            return tavily

        def _local(query):
            used.append("local")
            return local

        monkeypatch.setattr(app_module, "search_web_tavily", _tavily)
        monkeypatch.setattr(bo, "local_smart_search", _local)
        monkeypatch.setattr(bo, "_SEARCH_AVAILABLE", search_available)
        return bo.execute_task(TASK, {"query": "who is al ronge"}), used

    return _run


def test_search_task_asks_tavily_first(search):
    result, used = search({"sources": [{"title": "Air Ronge",
                                        "content": "a northern village"}]})

    assert used == ["tavily"]                     # scraper never consulted
    assert "Air Ronge" in result["results"]
    assert "a northern village" in result["results"]


def test_search_task_falls_back_to_the_scraper_when_tavily_is_empty(search):
    result, used = search({"sources": []}, local="scraped text")

    assert used == ["tavily", "local"]
    assert result["results"] == "scraped text"


def test_search_task_falls_back_to_the_scraper_when_tavily_raises(search):
    def _boom(query):
        raise RuntimeError("429 rate limit")

    result, used = search(_boom, local="scraped text")

    assert used == ["tavily", "local"]
    assert result["results"] == "scraped text"


def test_search_task_still_reports_the_query_it_ran(search):
    result, _ = search({"sources": [{"title": "Air Ronge", "content": "x"}]})

    assert result["query"] == "who is al ronge"


def test_search_task_results_stay_capped(search):
    result, _ = search({"sources": []}, local="x" * 9000)

    assert len(result["results"]) <= 4000


def test_search_task_reports_unavailable_only_when_nothing_works(search):
    result, _ = search({"sources": []}, local="", search_available=False)

    assert result["error"] == "search unavailable"


def test_tavily_alone_is_enough_when_the_local_engine_is_missing(search):
    """Losing local_engine must no longer mean losing search entirely."""
    result, _ = search({"sources": [{"title": "Air Ronge", "content": "x"}]},
                       search_available=False)

    assert "error" not in result
    assert "Air Ronge" in result["results"]
