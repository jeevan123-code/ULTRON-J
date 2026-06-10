"""Tests for the Phase 3c HANDS_ON takeover branch added to proactive_offer."""
from unittest.mock import patch, MagicMock

import pytest

import proactive_offer as po
from consent_types import ConsentMode
from intent_types import ExecutionPlan
from improvement_types import Suggestion
from action_types import ActionEvent, ActionKind


@pytest.fixture(autouse=True)
def _reset():
    po._reset_for_test()
    yield
    po._reset_for_test()


def _suggestion() -> Suggestion:
    return Suggestion(
        kind="batch_rename",
        summary="rename 5 files?",
        template="batch_rename_script",
        supporting_events=[
            ActionEvent(ts=float(i), kind=ActionKind.FILE_RENAME, target=f"f{i}")
            for i in range(5)
        ],
        confidence=0.9,
    )


def _takeover_plan() -> ExecutionPlan:
    return ExecutionPlan(
        steps=[{"action": "takeover", "args": {"type_text": "rename all"}}],
        pre_checks=[], rationale="phase3c demo",
    )


def test_offer_takeover_suggestion_stores_pending():
    po.offer_takeover_suggestion(_suggestion(), _takeover_plan())
    pending = po.peek_pending_offer()
    assert pending is not None
    assert pending.get("kind") == "improvement"
    assert pending.get("suggestion_kind") == "batch_rename"


def test_hands_on_takeover_invokes_takeover_executor_when_flag_on(monkeypatch):
    fake_exec = MagicMock(return_value={"executed": True, "mode": "type_text"})
    monkeypatch.setenv("ULTRON_PHASE3C_ENABLED", "1")
    monkeypatch.setattr(po, "_execute_takeover_plan", fake_exec)
    po.offer_takeover_suggestion(_suggestion(), _takeover_plan())
    result = po.confirm_offer(ConsentMode.HANDS_ON)
    assert result["confirmed"] is True
    assert result["executed"] is True
    fake_exec.assert_called_once()
    plan_arg = fake_exec.call_args[0][0]
    assert plan_arg.steps[0]["action"] == "takeover"
    assert po.peek_pending_offer() is None


def test_hands_on_takeover_short_circuits_research(monkeypatch):
    """When pending has a takeover_plan + flag on, research must NOT be called."""
    fake_research = MagicMock()
    fake_takeover = MagicMock(return_value={"executed": True})
    monkeypatch.setenv("ULTRON_PHASE3C_ENABLED", "1")
    monkeypatch.setattr(po, "_execute_plan", fake_research)
    monkeypatch.setattr(po, "_execute_takeover_plan", fake_takeover)
    po.offer_takeover_suggestion(_suggestion(), _takeover_plan())
    po.confirm_offer(ConsentMode.HANDS_ON)
    fake_research.assert_not_called()
    fake_takeover.assert_called_once()


def test_hands_on_takeover_flag_off_clears_pending_and_no_call(monkeypatch):
    """Flag off → pending is dropped, no executor is called (safe default)."""
    monkeypatch.delenv("ULTRON_PHASE3C_ENABLED", raising=False)
    fake_research = MagicMock()
    fake_takeover = MagicMock()
    monkeypatch.setattr(po, "_execute_plan", fake_research)
    monkeypatch.setattr(po, "_execute_takeover_plan", fake_takeover)
    po.offer_takeover_suggestion(_suggestion(), _takeover_plan())
    result = po.confirm_offer(ConsentMode.HANDS_ON)
    fake_research.assert_not_called()
    fake_takeover.assert_not_called()
    assert result["confirmed"] is False
    assert result.get("reason") == "phase3c_disabled"
    assert po.peek_pending_offer() is None


def test_decline_on_takeover_offer_clears_pending(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE3C_ENABLED", "1")
    fake_takeover = MagicMock()
    monkeypatch.setattr(po, "_execute_takeover_plan", fake_takeover)
    po.offer_takeover_suggestion(_suggestion(), _takeover_plan())
    result = po.confirm_offer(ConsentMode.DECLINE)
    assert result["confirmed"] is False
    fake_takeover.assert_not_called()
    assert po.peek_pending_offer() is None


def test_takeover_executor_exception_is_handled(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE3C_ENABLED", "1")
    monkeypatch.setattr(
        po, "_execute_takeover_plan",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    po.offer_takeover_suggestion(_suggestion(), _takeover_plan())
    result = po.confirm_offer(ConsentMode.HANDS_ON)
    assert result["confirmed"] is True
    assert result["executed"] is False
    assert "boom" in result.get("error", "")
    assert po.peek_pending_offer() is None
