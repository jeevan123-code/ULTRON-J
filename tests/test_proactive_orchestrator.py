"""Tests for proactive_orchestrator — context-driven device scenarios."""
import pytest

import proactive_orchestrator as po
from proactive_orchestrator import ContextRule, register_rule, evaluate, orchestrate


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(po, "_STATE_PATH", str(tmp_path / "state.json"))
    dispatched = []
    monkeypatch.setattr(po, "_dispatch",
                        lambda a: dispatched.append(a) or {"ok": True})
    monkeypatch.setattr(po, "_notify", lambda m: None)
    po._reset_for_test()
    yield dispatched
    po._reset_for_test()


def _leaving_rule():
    return ContextRule(
        name="leaving_home",
        predicate=lambda c: (not c.get("person_present", True)) and c.get("hour", 0) >= 20,
        actions=[{"device": "smart_home", "action": "lock_doors"},
                 {"device": "smart_home", "action": "set_thermostat", "args": {"temp": 18}}],
        cooldown_seconds=3600,
    )


# ── pure evaluate ──────────────────────────────────────────────────────────
def test_evaluate_matches_condition():
    register_rule(_leaving_rule())
    fired = evaluate({"person_present": False, "hour": 22})
    assert [r.name for r in fired] == ["leaving_home"]
    assert evaluate({"person_present": True, "hour": 22}) == []


def test_bad_predicate_is_skipped():
    register_rule(ContextRule("boom", predicate=lambda c: 1 / 0, actions=[]))
    assert evaluate({}) == []       # no crash


# ── orchestrate: park by default (AMBER posture) ───────────────────────────
def test_default_parks_device_actions(_isolate, monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE20_AUTO", raising=False)
    register_rule(_leaving_rule())
    s = orchestrate({"person_present": False, "hour": 21})
    assert s["fired"] == 1 and s["parked"] == 1 and s["ran"] == 0
    assert _isolate == []            # no device actually actuated


def test_approved_runs_device_actions(_isolate):
    register_rule(_leaving_rule())
    s = orchestrate({"person_present": False, "hour": 21}, approved=True)
    assert s["ran"] == 1
    assert len(_isolate) == 2        # both device actions dispatched


def test_auto_flag_runs(_isolate, monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE20_AUTO", "1")
    register_rule(_leaving_rule())
    s = orchestrate({"person_present": False, "hour": 21})
    assert s["ran"] == 1
    assert len(_isolate) == 2


# ── cooldown prevents re-firing a standing condition every cycle ────────────
def test_cooldown_suppresses_repeat(_isolate):
    register_rule(_leaving_rule())
    ctx = {"person_present": False, "hour": 21}
    orchestrate(ctx, approved=True, now=1000.0)
    s2 = orchestrate(ctx, approved=True, now=1000.0 + 60)   # within cooldown
    assert s2["fired"] == 0 and s2["cooling_down"] == 1
    s3 = orchestrate(ctx, approved=True, now=1000.0 + 4000) # past cooldown
    assert s3["fired"] == 1
