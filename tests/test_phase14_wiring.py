"""Tests for the Phase 14 autonomous-loop wiring.

Isolate the wiring from goal_author internals (tested separately) by stubbing
goal_author.author; verify flag-gating and observation enrichment.
"""
import pytest

import autonomous_loop as al
import goal_author


def test_flag_off_is_noop(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE14_ENABLED", "0")
    called = {"n": 0}
    monkeypatch.setattr(goal_author, "author",
                        lambda obs: called.__setitem__("n", called["n"] + 1))
    obs = {}
    al._phase14_author_goals(obs)
    assert called["n"] == 0
    assert "phase14_summary" not in obs


def test_flag_on_runs_author_and_enriches(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE14_ENABLED", "1")
    seen = {}

    def _fake_author(obs):
        # capture that enrichment ran before author was called
        seen["failure_counts"] = obs.get("failure_counts")
        seen["recent_topics"] = obs.get("recent_topics")
        seen["known_topics"] = obs.get("known_topics")
        return {"proposed": 0, "created": 0, "parked": 0}

    monkeypatch.setattr(goal_author, "author", _fake_author)
    obs = {}
    al._phase14_author_goals(obs)
    assert obs.get("phase14_summary") == {"proposed": 0, "created": 0, "parked": 0}
    # enrichment keys were populated (types, not exact values — real sources)
    assert isinstance(seen["failure_counts"], dict)
    assert isinstance(seen["recent_topics"], list)
    assert isinstance(seen["known_topics"], list)


def test_enrich_populates_expected_keys():
    obs = {}
    al._phase14_enrich_observation(obs)
    assert isinstance(obs["failure_counts"], dict)
    assert isinstance(obs["recent_topics"], list)
    assert isinstance(obs["known_topics"], list)


def test_error_in_author_is_swallowed(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE14_ENABLED", "1")

    def _boom(obs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(goal_author, "author", _boom)
    obs = {}
    al._phase14_author_goals(obs)          # must not raise
    assert "phase14_error" in obs
