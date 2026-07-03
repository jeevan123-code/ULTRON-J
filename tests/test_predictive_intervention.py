"""Tests for predictive_intervention — anomalies -> remediation goals."""
import pytest

import goal_author as ga
import predictive_intervention as pi
from goal_author_types import GoalProposal


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ga, "_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(ga, "_notify", lambda m: None)
    created = []
    monkeypatch.setattr(ga, "_create_goal",
                        lambda p: created.append(p) or {"id": "g", "title": p.title})
    ga._reset_for_test()
    yield created
    ga._reset_for_test()


_ANOM = {"key": "mem_rising", "severity": "high",
         "summary": "Memory 88% and climbing; projected 95% in ~6 samples",
         "action": "Close unused apps or reduce local-model usage."}


# ── pure mapping ───────────────────────────────────────────────────────────
def test_remediation_for_maps_anomaly():
    p = pi.remediation_for(_ANOM)
    assert isinstance(p, GoalProposal)
    assert p.subject == "mem_rising"
    assert p.trigger == "predictive"
    assert p.priority == "high"
    assert "Close unused apps" in p.description


def test_remediation_for_rejects_malformed():
    assert pi.remediation_for({}) is None
    assert pi.remediation_for({"key": "x"}) is None       # no summary
    assert pi.remediation_for(None) is None


# ── intervene routes through goal_author gate (parks by default) ───────────
def test_intervene_parks_by_default(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE14_AUTO_GREEN", raising=False)
    s = pi.intervene([_ANOM])
    assert s["proposed"] == 1
    assert s["parked"] == 1
    assert ga.list_pending()[0]["subject"] == "mem_rising"


def test_intervene_dedups_repeat_anomaly(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE14_AUTO_GREEN", raising=False)
    pi.intervene([_ANOM])
    s2 = pi.intervene([_ANOM])                 # same key within cooldown
    assert s2["deduped"] == 1
    assert len(ga.list_pending()) == 1


def test_intervene_empty():
    assert pi.intervene([])["proposed"] == 0


# ── run() reads the anomaly log ────────────────────────────────────────────
def test_run_reads_predictive_monitor(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE14_AUTO_GREEN", raising=False)
    import predictive_monitor
    monkeypatch.setattr(predictive_monitor, "get_anomaly_log", lambda n=10: [_ANOM])
    s = pi.run()
    assert s["parked"] == 1


# ── mind_tick stage flag-gating ────────────────────────────────────────────
def test_mind_tick_stage_gated(monkeypatch):
    import mind_tick
    monkeypatch.setenv("ULTRON_PHASE22_ENABLED", "0")
    summary = {}
    mind_tick._stage_predictive(0.0, summary)
    assert summary["predictive_interventions"] == 0


def test_mind_tick_stage_runs(monkeypatch):
    import mind_tick, predictive_intervention
    monkeypatch.setenv("ULTRON_PHASE22_ENABLED", "1")
    monkeypatch.setattr(predictive_intervention, "run",
                        lambda: {"created": 1, "parked": 2})
    summary = {}
    mind_tick._stage_predictive(0.0, summary)
    assert summary["predictive_interventions"] == 3
