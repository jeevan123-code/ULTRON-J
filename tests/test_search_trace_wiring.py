"""search_web_tavily must leave a trace whenever it comes back empty.

search_trace is unit-tested in test_search_trace.py; this file covers the GLUE.

The seam is search_web_tavily itself rather than the /ask block, because the
function swallows every exception internally (app.py:498) and returns
{"summary": "", "sources": []}. Callers therefore never see the failure — the
`except Exception as _te` in /ask is unreachable, and the "error" key it sets
was always absent. Tracing here covers every caller at once: /ask,
voice_routes, react_engine and smart_browser_agent.
"""
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module      # noqa: E402
import search_trace           # noqa: E402


class _Resp:
    """Minimal stand-in for a requests Response."""

    def __init__(self, payload=None, raises=None):
        self._payload = payload or {}
        self._raises = raises

    def raise_for_status(self):
        if self._raises:
            raise self._raises

    def json(self):
        return self._payload


@pytest.fixture
def search(monkeypatch, capsys):
    """Call search_web_tavily against a stubbed HTTP layer.

    Returns a callable yielding (result, [search] log lines).
    """
    def _run(post, api_key="test-key"):
        monkeypatch.setattr(app_module, "TAVILY_API_KEY", api_key)
        monkeypatch.setattr(requests, "post", post)
        capsys.readouterr()                  # drop anything logged before this
        result = app_module.search_web_tavily("who is al ronge")
        lines = [ln for ln in capsys.readouterr().out.splitlines()
                 if ln.startswith(search_trace.PREFIX)]
        return result, lines

    return _run


def test_logs_the_exception_when_the_request_raises(search):
    def _boom(*a, **k):
        raise requests.Timeout("timed out after 3s")

    result, lines = search(_boom)

    assert len(lines) == 1
    assert "tavily" in lines[0]
    assert "timed out after 3s" in lines[0]
    assert result["sources"] == []          # callers still get the safe shape


def test_logs_an_http_error_status(search):
    err = requests.HTTPError("429 Too Many Requests")
    _, lines = search(lambda *a, **k: _Resp(raises=err))

    assert len(lines) == 1
    assert "429 Too Many Requests" in lines[0]


def test_logs_a_successful_call_that_returned_no_results(search):
    """The path that actually fired on 2026-07-29 — HTTP 200, zero sources."""
    _, lines = search(lambda *a, **k: _Resp({"results": [], "answer": ""}))

    assert len(lines) == 1
    assert "0 sources" in lines[0]


def test_logs_the_missing_api_key(search):
    _, lines = search(lambda *a, **k: _Resp(), api_key="")

    assert len(lines) == 1
    assert "no_tavily_key" in lines[0]


def test_logs_the_query_so_a_failure_can_be_traced_to_a_question(search):
    _, lines = search(lambda *a, **k: _Resp({"results": []}))

    assert "who is al ronge" in lines[0]


def test_logs_nothing_when_the_search_succeeds(search):
    result, lines = search(lambda *a, **k: _Resp(
        {"results": [{"title": "Air Ronge", "content": "a village"}],
         "answer": "a northern village"}))

    assert lines == []
    assert len(result["sources"]) == 1
