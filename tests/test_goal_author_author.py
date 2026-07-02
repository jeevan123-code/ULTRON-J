"""Tests for the goal_author orchestrator: dedup, cap, safety gating, park/approve."""
import pytest

import goal_author as ga
from goal_author import (
    author, list_pending, approve, reject,
    MAX_SELF_GOALS_PER_DAY, KNOWLEDGE_GAP_THRESHOLD, REPEATED_FAILURE_THRESHOLD,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # Point state at a tmp file; stub the two I/O seams so no real goal store /
    # notifications are touched.
    monkeypatch.setattr(ga, "_STATE_PATH", str(tmp_path / "state.json"))
    created = []
    monkeypatch.setattr(ga, "_create_goal",
                        lambda p: created.append(p) or {"id": f"g{len(created)}",
                                                        "title": p.title})
    monkeypatch.setattr(ga, "_notify", lambda msg: None)
    ga._reset_for_test()
    yield created
    ga._reset_for_test()


def _gap_obs(topic="graphql", n=KNOWLEDGE_GAP_THRESHOLD):
    return {"recent_topics": [topic] * n, "known_topics": []}


# ── default posture: everything parked, nothing auto-created ─────────────────
def test_default_parks_green_instead_of_creating(monkeypatch, _isolate):
    monkeypatch.delenv("ULTRON_PHASE14_AUTO_GREEN", raising=False)
    s = author(_gap_obs())
    assert s["created"] == 0
    assert s["parked"] == 1
    assert _isolate == []                      # _create_goal never called
    assert len(list_pending()) == 1


# ── auto-green ON: green goals auto-create ──────────────────────────────────
def test_auto_green_creates_goal(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE14_AUTO_GREEN", "1")
    s = author(_gap_obs())
    assert s["created"] == 1
    assert len(_isolate) == 1
    assert _isolate[0].title.startswith("Research 'graphql'")


# ── dedup: same proposal within cooldown only acts once ─────────────────────
def test_dedup_cooldown_blocks_second_time(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE14_AUTO_GREEN", "1")
    author(_gap_obs())
    s2 = author(_gap_obs())
    assert s2["created"] == 0
    assert s2["deduped"] == 1
    assert len(_isolate) == 1                   # still only one goal total


# ── daily cap: never exceed MAX_SELF_GOALS_PER_DAY auto-creations ────────────
def test_daily_cap_enforced(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE14_AUTO_GREEN", "1")
    # Feed more distinct gap topics than the cap allows.
    topics = [f"topic{i}" for i in range(MAX_SELF_GOALS_PER_DAY + 3)]
    obs = {"recent_topics": [t for t in topics for _ in range(KNOWLEDGE_GAP_THRESHOLD)],
           "known_topics": []}
    s = author(obs)
    assert s["created"] == MAX_SELF_GOALS_PER_DAY
    assert s["parked"] >= 1                     # overflow parked, not lost


# ── RED proposals are dropped, never created or parked ──────────────────────
def test_red_proposal_dropped(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE14_AUTO_GREEN", "1")
    # "delete" in the topic -> classify_safety forces RED.
    obs = {"recent_topics": ["delete"] * KNOWLEDGE_GAP_THRESHOLD, "known_topics": []}
    s = author(obs)
    assert s["dropped_red"] == 1
    assert s["created"] == 0
    assert list_pending() == []


# ── approve a parked proposal -> creates the goal, removes from pending ──────
def test_approve_creates_and_clears(monkeypatch, _isolate):
    monkeypatch.delenv("ULTRON_PHASE14_AUTO_GREEN", raising=False)
    author(_gap_obs())
    pend = list_pending()
    assert len(pend) == 1
    key = pend[0]["dedup_key"]
    goal = approve(key)
    assert goal is not None
    assert len(_isolate) == 1                   # _create_goal invoked on approve
    assert list_pending() == []


def test_reject_clears_without_creating(monkeypatch, _isolate):
    monkeypatch.delenv("ULTRON_PHASE14_AUTO_GREEN", raising=False)
    author(_gap_obs())
    key = list_pending()[0]["dedup_key"]
    assert reject(key) is True
    assert list_pending() == []
    assert _isolate == []
    assert reject("nonexistent") is False
