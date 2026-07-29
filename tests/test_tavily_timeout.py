"""Tavily must survive a slow response instead of dropping to the scraper.

Measured 2026-07-29: Tavily answers in ~0.95s median, 1.73s worst of 8 calls —
but it does stall, and two live calls that day blew past the hardcoded
timeout=3 and were killed. Each kill dropped the query onto the DuckDuckGo
scraper, which answered 2 of 6 attempts.

So the budget was too tight for a backend that is normally a second away, and
a transient stall was indistinguishable from "no results".
"""
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module      # noqa: E402


class _Resp:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


_HIT = {"results": [{"title": "Air Ronge", "content": "a village"}],
        "answer": "a northern village"}


@pytest.fixture
def call(monkeypatch):
    """Call search_web_tavily against a scripted sequence of HTTP outcomes.

    Returns a callable yielding (result, timeouts_passed_to_post).
    """
    monkeypatch.setattr(app_module, "TAVILY_API_KEY", "test-key")

    def _run(*outcomes):
        seen = []
        script = list(outcomes)

        def _post(*a, **kw):
            seen.append(kw.get("timeout"))
            outcome = script.pop(0) if script else _Resp(_HIT)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(requests, "post", _post)
        return app_module.search_web_tavily("who is al ronge"), seen

    return _run


def test_a_stall_is_retried_rather_than_abandoned(call):
    result, seen = call(requests.Timeout("read timed out"), _Resp(_HIT))

    assert len(seen) == 2                      # retried
    assert len(result["sources"]) == 1         # and recovered


def test_a_dropped_connection_is_retried(call):
    result, seen = call(requests.ConnectionError("reset by peer"), _Resp(_HIT))

    assert len(seen) == 2
    assert len(result["sources"]) == 1


def test_it_gives_up_after_one_retry(call):
    result, seen = call(requests.Timeout("t"), requests.Timeout("t"),
                        requests.Timeout("t"))

    assert len(seen) == 2                      # not an unbounded retry loop
    assert result["sources"] == []             # callers still get a safe shape


def test_a_rejected_key_is_not_retried(call):
    """Only transient faults deserve a second attempt — 401 will never pass."""
    _, seen = call(requests.HTTPError("401 Unauthorized"))

    assert len(seen) == 1


def test_the_budget_clears_the_observed_worst_case(call):
    _, seen = call(_Resp(_HIT))

    assert seen[0] >= 8            # 1.73s worst case measured, 3s was killing it


def test_a_healthy_call_is_not_retried(call):
    _, seen = call(_Resp(_HIT))

    assert len(seen) == 1


def test_the_budget_is_configurable(monkeypatch, call):
    monkeypatch.setenv("ULTRON_TAVILY_TIMEOUT", "20")
    _, seen = call(_Resp(_HIT))

    assert seen[0] == 20.0
