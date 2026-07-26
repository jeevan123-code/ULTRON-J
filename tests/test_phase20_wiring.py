"""Phase 20 wiring — proactive device orchestration runs inside the mind tick.

The orchestrator was built with an `orchestrate(context)` entry point and no
caller, so it never saw a context. This stage supplies a real one each tick.

Rules themselves stay user-supplied via proactive_orchestrator.register_rule();
with none registered the stage is a safe no-op that reports zero.
"""
import pytest

import mind_tick
import proactive_orchestrator as po


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(po, "_STATE_PATH", str(tmp_path / "po.json"))
    po._reset_for_test()
    yield
    po._reset_for_test()


def test_stage_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE20_ENABLED", raising=False)
    called = []
    monkeypatch.setattr(po, "orchestrate", lambda *a, **k: called.append(a))
    summary = {}
    mind_tick._stage_orchestration(0.0, summary)
    assert called == []
    assert summary["device_scenarios"] == 0


def test_stage_calls_orchestrate_when_enabled(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE20_ENABLED", "1")
    seen = {}

    def _fake(context, **kw):
        seen.update(context)
        return {"fired": 2, "ran": 0, "parked": 2, "cooling_down": 0}

    monkeypatch.setattr(po, "orchestrate", _fake)
    summary = {}
    mind_tick._stage_orchestration(0.0, summary)
    assert summary["device_scenarios"] == 2


def test_context_carries_real_time_signals(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE20_ENABLED", "1")
    seen = {}
    monkeypatch.setattr(po, "orchestrate",
                        lambda context, **kw: seen.update(context) or
                        {"fired": 0, "ran": 0, "parked": 0, "cooling_down": 0})
    mind_tick._stage_orchestration(0.0, {})
    assert isinstance(seen.get("hour"), int) and 0 <= seen["hour"] <= 23
    assert seen.get("time_of_day") in {"morning", "afternoon", "evening", "night"}
    assert isinstance(seen.get("weekday"), int)


def test_stage_failure_does_not_break_the_tick(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE20_ENABLED", "1")
    monkeypatch.setattr(po, "orchestrate",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    summary = {}
    mind_tick._stage_orchestration(0.0, summary)  # must not raise
    assert "orchestration_error" in summary


def test_tick_reports_the_new_stage(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE20_ENABLED", raising=False)
    summary = mind_tick.tick(now=0.0)
    assert "device_scenarios" in summary


def test_no_rules_registered_is_a_safe_noop(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE20_ENABLED", "1")
    po.clear_rules()
    summary = {}
    mind_tick._stage_orchestration(0.0, summary)
    assert summary["device_scenarios"] == 0
