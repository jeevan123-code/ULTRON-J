"""Tests for multi_device_coordinator — registry + trigger match + run."""
from unittest.mock import MagicMock

import pytest

import multi_device_coordinator as mdc
from scenario_types import Scenario, ScenarioStep


@pytest.fixture(autouse=True)
def _reset():
    mdc._reset_for_test()
    yield
    mdc._reset_for_test()


def _scn(name="bedtime", phrases=None, steps=None):
    return Scenario(
        name=name,
        trigger_phrases=phrases or ["bedtime"],
        steps=steps or [ScenarioStep("laptop", "lock"), ScenarioStep("smart_home", "lights_off")],
    )


def test_match_trigger_empty_registry_returns_none():
    assert mdc.match_trigger("bedtime") is None


def test_register_and_match_trigger():
    sc = _scn()
    mdc.register(sc)
    out = mdc.match_trigger("bedtime now")
    assert out is sc


def test_match_trigger_case_insensitive():
    mdc.register(_scn(name="bp", phrases=["house party"]))
    assert mdc.match_trigger("Jarvis, HOUSE party").name == "bp"


def test_match_trigger_no_match_returns_none():
    mdc.register(_scn())
    assert mdc.match_trigger("good morning") is None


def test_run_dispatches_each_step_to_dispatcher(monkeypatch):
    calls = []

    def fake_dispatch(step):
        calls.append((step.target, step.action))
        return {"ok": True}

    monkeypatch.setattr(mdc, "_dispatch_step", fake_dispatch)
    sc = _scn(steps=[
        ScenarioStep("laptop", "lock"),
        ScenarioStep("phone", "silence"),
        ScenarioStep("smart_home", "lights_off"),
    ])
    result = mdc.run(sc)
    assert calls == [("laptop", "lock"), ("phone", "silence"), ("smart_home", "lights_off")]
    assert all(r["ok"] for r in result.values())


def test_run_continues_on_step_failure(monkeypatch):
    def fake_dispatch(step):
        if step.target == "phone":
            raise RuntimeError("no telegram")
        return {"ok": True, "target": step.target}

    monkeypatch.setattr(mdc, "_dispatch_step", fake_dispatch)
    sc = _scn(steps=[
        ScenarioStep("laptop", "lock"),
        ScenarioStep("phone", "silence"),
        ScenarioStep("smart_home", "lights_off"),
    ])
    result = mdc.run(sc)
    assert result[0]["ok"] is True
    assert result[1].get("error")
    assert "no telegram" in result[1]["error"]
    assert result[2]["ok"] is True


def test_dispatch_step_laptop_routes_to_computer_control(monkeypatch):
    captured = {}

    def fake_lock():
        captured["called"] = True
        return {"success": True}

    monkeypatch.setattr(mdc, "_laptop_action", lambda action, args: fake_lock() if action == "lock" else {})
    result = mdc._dispatch_step(ScenarioStep("laptop", "lock"))
    assert result["success"] is True
    assert captured["called"] is True


def test_dispatch_step_unknown_target_returns_skipped():
    result = mdc._dispatch_step(ScenarioStep("toaster", "burn"))
    assert result.get("skipped") is True
