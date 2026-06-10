"""End-to-end Phase 3c: action_log -> suggester -> proactive_offer -> takeover."""
from unittest.mock import MagicMock

import pytest

import action_log
import improvement_suggester
import proactive_offer as po
from action_types import ActionEvent, ActionKind
from consent_types import ConsentMode
from intent_types import ExecutionPlan


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(action_log, "_PATH", str(tmp_path / "action_log.json"))
    action_log._reset_for_test()
    po._reset_for_test()
    yield
    action_log._reset_for_test()
    po._reset_for_test()


def test_end_to_end_batch_rename_suggestion_to_takeover(monkeypatch):
    # 1. user renames 5 files (recorded by some upstream observer)
    for i in range(5):
        action_log.record(ActionEvent(
            ts=float(i), kind=ActionKind.FILE_RENAME, target=f"draft_{i}.md",
        ))

    # 2. suggester scans the log
    events = action_log.recent(now=100.0, within_seconds=3600)
    suggestions = improvement_suggester.analyze(events)
    assert any(s.kind == "batch_rename" for s in suggestions)
    s = next(x for x in suggestions if x.kind == "batch_rename")

    # 3. offer is parked with a takeover plan
    plan = ExecutionPlan(
        steps=[{"action": "takeover", "args": {"type_text": "for f in *.md; do mv $f new_$f; done"}}],
        pre_checks=[], rationale="batch rename via shell",
    )
    po.offer_takeover_suggestion(s, plan)
    assert po.peek_pending_offer() is not None

    # 4. user replies HANDS_ON; flag is on, takeover_executor is stubbed
    monkeypatch.setenv("ULTRON_PHASE3C_ENABLED", "1")
    fake_takeover = MagicMock(return_value={"executed": True, "mode": "type_text"})
    monkeypatch.setattr(po, "_execute_takeover_plan", fake_takeover)

    result = po.confirm_offer(ConsentMode.HANDS_ON)
    assert result["confirmed"] is True
    assert result["executed"] is True
    fake_takeover.assert_called_once()
    invoked_plan = fake_takeover.call_args[0][0]
    assert invoked_plan.steps[0]["action"] == "takeover"
    assert po.peek_pending_offer() is None


def test_flag_off_full_pipeline_short_circuits(monkeypatch):
    # Same flow but with the kill-switch
    for i in range(5):
        action_log.record(ActionEvent(
            ts=float(i), kind=ActionKind.FILE_RENAME, target=f"x_{i}.md",
        ))

    suggestions = improvement_suggester.analyze(
        action_log.recent(now=100.0, within_seconds=3600)
    )
    s = next(x for x in suggestions if x.kind == "batch_rename")

    plan = ExecutionPlan(
        steps=[{"action": "takeover", "args": {"type_text": "noop"}}],
        pre_checks=[], rationale="",
    )
    po.offer_takeover_suggestion(s, plan)

    monkeypatch.delenv("ULTRON_PHASE3C_ENABLED", raising=False)
    fake_takeover = MagicMock()
    monkeypatch.setattr(po, "_execute_takeover_plan", fake_takeover)

    result = po.confirm_offer(ConsentMode.HANDS_ON)
    fake_takeover.assert_not_called()
    assert result["confirmed"] is False
    assert result.get("reason") == "phase3c_disabled"
