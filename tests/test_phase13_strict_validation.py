"""Tests for Phase 13 — strict_validation kwarg on chain_executor.execute_chain."""
from unittest.mock import MagicMock

import pytest

import chain_executor
from intent_types import ExecutionPlan


def _plan(*steps):
    return ExecutionPlan(steps=list(steps), pre_checks=[], rationale="test")


def test_strict_off_default_unknown_action_still_executes(monkeypatch):
    """Default behavior preserved: bad action runs through and returns failure."""
    fake_research = MagicMock(return_value={"executed": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", fake_research)
    plan = _plan({"action": "fake_thing", "args": {}})
    out = chain_executor.execute_chain(plan)
    assert len(out) == 1
    assert out[0]["ok"] is False
    # Without strict mode, the chain still attempts dispatch (and the unknown
    # action handler in _run_one returns its own error).


def test_strict_on_unknown_action_short_circuits(monkeypatch):
    fake_research = MagicMock(return_value={"executed": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", fake_research)
    plan = _plan({"action": "fake_thing", "args": {}})
    out = chain_executor.execute_chain(plan, strict_validation=True)
    assert len(out) == 1
    assert out[0]["ok"] is False
    assert out[0].get("skipped") is True
    assert out[0].get("reason") == "validation_failed"
    fake_research.assert_not_called()


def test_strict_on_missing_required_arg_short_circuits(monkeypatch):
    fake_research = MagicMock(return_value={"executed": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", fake_research)
    plan = _plan({"action": "research", "args": {}})  # missing topic
    out = chain_executor.execute_chain(plan, strict_validation=True)
    assert out[0].get("reason") == "validation_failed"
    fake_research.assert_not_called()


def test_strict_on_warning_only_still_executes(monkeypatch):
    """Warnings (not errors) shouldn't block execution under strict mode."""
    fake_research = MagicMock(return_value={"executed": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", fake_research)
    plan = _plan({
        "action": "research", "args": {"topic": "AAPL"},
        "if_prev_failed": True,  # step 0 with if_prev_failed -> warning, not error
    })
    out = chain_executor.execute_chain(plan, strict_validation=True)
    # The validator emits a warning but no error; strict mode allows it.
    # The conditional logic will skip it because there's no prev — but that's
    # the EXECUTOR's behavior, not the validator blocking.
    assert out[0].get("skipped") is True
    assert out[0].get("reason") == "condition_not_met"


def test_strict_on_valid_plan_runs_normally(monkeypatch):
    fake_research = MagicMock(return_value={"executed": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", fake_research)
    plan = _plan({"action": "research", "args": {"topic": "AAPL"}})
    out = chain_executor.execute_chain(plan, strict_validation=True)
    assert out[0]["ok"] is True
    fake_research.assert_called_once()


def test_strict_validation_attaches_issues_to_result(monkeypatch):
    """When validation blocks execution, the issues are surfaced in the result."""
    plan = _plan({"action": "alert", "args": {}})  # missing message
    out = chain_executor.execute_chain(plan, strict_validation=True)
    assert "validation_issues" in out[0]
    assert isinstance(out[0]["validation_issues"], list)
    assert len(out[0]["validation_issues"]) >= 1
    assert any("message" in i["message"].lower()
               for i in out[0]["validation_issues"])
