"""End-to-end Phase 3b: stuck event -> polite offer -> consent -> research."""
from unittest.mock import patch, MagicMock
import pytest

import proactive_offer as po
from consent_types import ConsentMode
from consent_manager import parse_consent
from struggle_types import (
    ScreenSnapshot, StuckEvent, StuckKind, SensitivityKind,
)


@pytest.fixture(autouse=True)
def _reset():
    po._reset_for_test()
    yield
    po._reset_for_test()


def _stuck(error: str = "NameError: name 'x' is not defined") -> StuckEvent:
    snap = ScreenSnapshot(
        ts=100.0, active_window="Code - main.py",
        error_text=error, error_signature="sig",
        sensitivity=SensitivityKind.NONE,
    )
    return StuckEvent(
        kind=StuckKind.ERROR_PERSISTENT,
        first_seen_ts=100.0, last_seen_ts=140.0, duration_seconds=40.0,
        snapshot=snap,
    )


def test_full_voice_only_flow_runs_research():
    speak = MagicMock()
    fake_exec = MagicMock(return_value={"executed": True})

    with patch.object(po, "_speak", speak), \
         patch.object(po, "_execute_plan", fake_exec):
        po.handle_stuck_event(_stuck("AttributeError: foo"))
        assert po.peek_pending_offer() is not None
        speak.assert_called_once_with("Sir, mind if I help?")

        mode = parse_consent("yes just tell me")
        assert mode == ConsentMode.VOICE_ONLY

        result = po.confirm_offer(mode)

    assert result["confirmed"] is True
    assert result["mode"] == "voice_only"
    fake_exec.assert_called_once()
    plan = fake_exec.call_args[0][0]
    assert plan.steps[0]["action"] == "research"
    assert "AttributeError" in plan.steps[0]["args"]["topic"]
    assert po.peek_pending_offer() is None


def test_full_decline_flow_does_not_research():
    speak = MagicMock()
    fake_exec = MagicMock()

    with patch.object(po, "_speak", speak), \
         patch.object(po, "_execute_plan", fake_exec):
        po.handle_stuck_event(_stuck())
        mode = parse_consent("no thanks")
        assert mode == ConsentMode.DECLINE
        result = po.confirm_offer(mode)

    assert result["confirmed"] is False
    fake_exec.assert_not_called()
    assert po.peek_pending_offer() is None


def test_ambiguous_response_keeps_pending():
    speak = MagicMock()
    with patch.object(po, "_speak", speak):
        po.handle_stuck_event(_stuck())

    mode = parse_consent("what's the weather like")
    assert mode == ConsentMode.NONE

    result = po.confirm_offer(mode)
    assert result["confirmed"] is False
    assert po.peek_pending_offer() is not None
