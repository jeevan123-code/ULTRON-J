"""Tests for chain_executor — multi-step ExecutionPlan dispatch."""
from unittest.mock import MagicMock

import pytest

import chain_executor
from intent_types import ExecutionPlan


def _plan(*steps):
    return ExecutionPlan(steps=list(steps), pre_checks=[], rationale="test")


def test_empty_plan_returns_empty_list():
    out = chain_executor.execute_chain(_plan())
    assert out == []


def test_research_step_dispatches_to_phase2_executor(monkeypatch):
    fake = MagicMock(return_value={"executed": True, "delivery": {}})
    monkeypatch.setattr(chain_executor, "_dispatch_research", fake)
    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "AAPL"}},
    ))
    assert len(out) == 1
    assert out[0]["ok"] is True
    fake.assert_called_once()


def test_alert_step_calls_mobile_bridge_alert(monkeypatch):
    fake = MagicMock(return_value={"sent": True})
    monkeypatch.setattr(chain_executor, "_dispatch_alert", fake)
    out = chain_executor.execute_chain(_plan(
        {"action": "alert", "args": {"message": "test alert", "priority": "high"}},
    ))
    assert out[0]["ok"] is True
    fake.assert_called_once_with("test alert", "high")


def test_announce_step_calls_voice_engine_tts(monkeypatch):
    fake = MagicMock(return_value=(b"audio", "edge"))
    monkeypatch.setattr(chain_executor, "_dispatch_announce", fake)
    out = chain_executor.execute_chain(_plan(
        {"action": "announce", "args": {"text": "Sir, ready."}},
    ))
    assert out[0]["ok"] is True
    assert out[0]["result"]["provider"] == "edge"


def test_scenario_step_runs_via_coordinator(monkeypatch):
    import multi_device_coordinator as mdc
    import scenarios_builtin as sb
    mdc._reset_for_test()
    sb.register_builtins()
    fake_run = MagicMock(return_value={0: {"ok": True}})
    monkeypatch.setattr(mdc, "run", fake_run)
    out = chain_executor.execute_chain(_plan(
        {"action": "scenario", "args": {"name": "house_party"}},
    ))
    assert out[0]["ok"] is True
    fake_run.assert_called_once()


def test_unknown_action_records_failure_but_continues():
    out = chain_executor.execute_chain(_plan(
        {"action": "fake_thing", "args": {}},
        {"action": "research", "args": {"topic": "x"}},
    ))
    assert len(out) == 1  # stops at first failure by default
    assert out[0]["ok"] is False


def test_continue_on_failure_runs_subsequent_steps(monkeypatch):
    monkeypatch.setattr(chain_executor, "_dispatch_research",
                        MagicMock(return_value={"executed": True}))
    out = chain_executor.execute_chain(_plan(
        {"action": "fake_thing", "args": {}, "continue_on_failure": True},
        {"action": "research", "args": {"topic": "x"}},
    ))
    assert len(out) == 2
    assert out[0]["ok"] is False
    assert out[1]["ok"] is True


def test_multi_step_success_returns_all_results(monkeypatch):
    monkeypatch.setattr(chain_executor, "_dispatch_research",
                        MagicMock(return_value={"executed": True}))
    monkeypatch.setattr(chain_executor, "_dispatch_alert",
                        MagicMock(return_value={"sent": True}))
    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "x"}},
        {"action": "alert", "args": {"message": "done"}},
    ))
    assert len(out) == 2
    assert all(r["ok"] for r in out)


def test_step_can_reference_previous_step_result(monkeypatch):
    """A step's args can use {{prev_result}} to inject the previous step's result."""
    monkeypatch.setattr(chain_executor, "_dispatch_research",
                        MagicMock(return_value={"executed": True, "summary": "AAPL up 3%"}))

    captured_msg = {}
    def _capture_alert(message, priority):
        captured_msg["text"] = message
        return {"sent": True}
    monkeypatch.setattr(chain_executor, "_dispatch_alert", _capture_alert)

    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "AAPL"}},
        {"action": "alert", "args": {"message": "Research: {{prev.summary}}"}},
    ))
    assert all(r["ok"] for r in out)
    assert "AAPL up 3%" in captured_msg["text"]


def test_exception_in_step_does_not_propagate(monkeypatch):
    monkeypatch.setattr(chain_executor, "_dispatch_alert",
                        MagicMock(side_effect=RuntimeError("kapow")))
    out = chain_executor.execute_chain(_plan(
        {"action": "alert", "args": {"message": "x"}},
    ))
    assert out[0]["ok"] is False
    assert "kapow" in out[0]["error"]
