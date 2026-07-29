"""Tests for search_trace — the record of WHY a web search degraded.

The gap this closes: app.py caught Tavily exceptions into
`{"sources": [], "error": ...}` and nothing ever read that key, so a failed
search left no trace anywhere. When the user asked why Ultron fell back to
the scraper on 2026-07-29 the evidence had already been thrown away.

Companion to search_disclosure: that one tells the MODEL a search came back
empty, this one tells the OPERATOR why.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import search_trace  # noqa: E402


# ── the three degradation modes each leave a line ────────────────────────────

def test_records_the_exception_when_a_backend_raises():
    line = search_trace.record("tavily", "who is al ronge",
                               error=RuntimeError("429 rate limit"))

    assert "tavily" in line
    assert "429 rate limit" in line
    assert "who is al ronge" in line


def test_records_an_empty_result_that_raised_nothing():
    """The mode that actually bit us: no exception, just zero sources."""
    line = search_trace.record("tavily", "who is ultron jay", sources=0)

    assert "tavily" in line
    assert "0 sources" in line
    assert "who is ultron jay" in line


def test_records_a_backend_skipped_for_a_missing_key():
    line = search_trace.record("tavily", "btc price", skipped="no_tavily_key")

    assert "tavily" in line
    assert "no_tavily_key" in line


# ── success is silent ────────────────────────────────────────────────────────

def test_a_successful_search_records_nothing():
    assert search_trace.record("tavily", "btc price", sources=5) == ""


def test_sources_present_alongside_an_error_still_records_the_error():
    """A backend that partially failed is still worth a line."""
    line = search_trace.record("tavily", "btc price", sources=5,
                               error=ValueError("truncated response"))

    assert "truncated response" in line


# ── it is diagnostics, so it must never become the reason a reply breaks ─────

def test_never_raises_on_unprintable_input():
    class Explodes:
        def __str__(self):
            raise ValueError("boom")

    line = search_trace.record("tavily", Explodes(), error=Explodes())

    assert isinstance(line, str)


def test_long_queries_are_truncated_so_one_failure_stays_one_line():
    line = search_trace.record("tavily", "x" * 5000, sources=0)

    assert len(line) < 400
    assert "\n" not in line


def test_the_line_is_greppable_by_a_single_stable_prefix():
    for line in (
        search_trace.record("tavily", "q", error=RuntimeError("e")),
        search_trace.record("tavily", "q", sources=0),
        search_trace.record("tavily", "q", skipped="no_tavily_key"),
    ):
        assert line.startswith(search_trace.PREFIX)


def test_the_line_is_printed_so_it_reaches_the_server_log(capsys):
    search_trace.record("tavily", "who is al ronge", sources=0)

    assert "who is al ronge" in capsys.readouterr().out
