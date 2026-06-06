"""End-to-end test for phase2_executor."""
import json
from unittest.mock import patch, MagicMock
import pytest

import phase2_executor as p2x
from intent_types import ExecutionPlan
from tests.fixtures.research_responses import wheat_rust_report


def _research_plan(topic: str = "wheat leaf rust") -> ExecutionPlan:
    return ExecutionPlan(
        steps=[{"action": "research", "args": {"topic": topic}}],
        pre_checks=[],
        rationale="user asked to research.",
    )


def test_execute_runs_research_and_delivers():
    plan = _research_plan()
    canned = wheat_rust_report()

    fake_vs = MagicMock()
    with patch.object(p2x, "_research", return_value=canned), \
         patch("delivery_manager._speak", new=MagicMock()) as mock_speak, \
         patch("research_facts._get_vector_store", return_value=fake_vs):
        result = p2x.execute(plan)

    assert result["executed"] is True
    assert result["action"] == "research"
    assert result["delivery"]["spoken"] is True
    assert result["delivery"]["card"]["query"] == "wheat leaf rust"
    mock_speak.assert_called_once()


def test_execute_returns_skipped_for_non_research_plan():
    plan = ExecutionPlan(steps=[{"action": "chat_reply", "args": {}}], pre_checks=[], rationale="")
    result = p2x.execute(plan)
    assert result["executed"] is False
    assert result["action"] == "chat_reply"


def test_execute_handles_empty_plan():
    plan = ExecutionPlan(steps=[], pre_checks=[], rationale="")
    result = p2x.execute(plan)
    assert result["executed"] is False
    assert result["action"] is None


def test_execute_stores_verified_facts():
    plan = _research_plan()
    canned = wheat_rust_report()
    fake_vs = MagicMock()
    with patch.object(p2x, "_research", return_value=canned), \
         patch("delivery_manager._speak", new=MagicMock()), \
         patch("research_facts._get_vector_store", return_value=fake_vs):
        p2x.execute(plan)
    # facts above 0.6 should have been stored
    assert fake_vs.remember.called
