"""Tests for proactive_offer — handle_stuck_event, pending state, confirm_offer."""
from unittest.mock import patch, MagicMock
import pytest

import proactive_offer as po
from consent_types import ConsentMode
from struggle_types import (
    ScreenSnapshot, StuckEvent, StuckKind, SensitivityKind,
)


@pytest.fixture(autouse=True)
def _reset():
    po._reset_for_test()
    yield
    po._reset_for_test()


def _stuck_event(error: str = "NameError: name 'x' is not defined") -> StuckEvent:
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


def test_handle_stuck_event_speaks_polite_offer():
    speak = MagicMock()
    with patch.object(po, "_speak", speak):
        po.handle_stuck_event(_stuck_event())
    speak.assert_called_once()
    arg = speak.call_args[0][0]
    assert "mind if i help" in arg.lower()


def test_handle_stuck_event_sets_pending_offer():
    with patch.object(po, "_speak", MagicMock()):
        po.handle_stuck_event(_stuck_event("TypeError"))
    pending = po.peek_pending_offer()
    assert pending is not None
    assert pending["error_text"] == "TypeError"


def test_handle_stuck_event_rate_limited():
    """Second stuck event within rate limit must NOT speak again."""
    speak = MagicMock()
    with patch.object(po, "_speak", speak):
        po.handle_stuck_event(_stuck_event("err1"))
        po.handle_stuck_event(_stuck_event("err2"))
    speak.assert_called_once()


def test_handle_stuck_event_after_rate_limit_speaks_again(monkeypatch):
    speak = MagicMock()
    with patch.object(po, "_speak", speak):
        po.handle_stuck_event(_stuck_event("err1"))
        # Advance the "last offer" time past the rate-limit window
        po._last_offer_at = po._last_offer_at - po._RATE_LIMIT_SECONDS - 1
        po.handle_stuck_event(_stuck_event("err2"))
    assert speak.call_count == 2


def test_confirm_offer_hands_on_runs_research_and_clears_pending():
    fake_exec = MagicMock(return_value={"executed": True})
    with patch.object(po, "_speak", MagicMock()), \
         patch.object(po, "_execute_plan", fake_exec):
        po.handle_stuck_event(_stuck_event("KeyError: 'foo'"))
        result = po.confirm_offer(ConsentMode.HANDS_ON)
    assert result["confirmed"] is True
    assert result["mode"] == "hands_on"
    assert po.peek_pending_offer() is None
    fake_exec.assert_called_once()
    plan = fake_exec.call_args[0][0]
    assert plan.steps[0]["action"] == "research"
    assert "KeyError" in plan.steps[0]["args"]["topic"]


def test_confirm_offer_voice_only_runs_research():
    fake_exec = MagicMock(return_value={"executed": True})
    with patch.object(po, "_speak", MagicMock()), \
         patch.object(po, "_execute_plan", fake_exec):
        po.handle_stuck_event(_stuck_event("AttributeError"))
        result = po.confirm_offer(ConsentMode.VOICE_ONLY)
    assert result["confirmed"] is True
    fake_exec.assert_called_once()


def test_confirm_offer_decline_clears_pending_without_research():
    fake_exec = MagicMock()
    with patch.object(po, "_speak", MagicMock()), \
         patch.object(po, "_execute_plan", fake_exec):
        po.handle_stuck_event(_stuck_event("err"))
        result = po.confirm_offer(ConsentMode.DECLINE)
    assert result["confirmed"] is False
    assert po.peek_pending_offer() is None
    fake_exec.assert_not_called()


def test_confirm_offer_no_pending_returns_noop():
    result = po.confirm_offer(ConsentMode.HANDS_ON)
    assert result["confirmed"] is False
    assert result.get("reason") == "no_pending_offer"


def test_confirm_offer_none_mode_keeps_pending():
    with patch.object(po, "_speak", MagicMock()):
        po.handle_stuck_event(_stuck_event())
    result = po.confirm_offer(ConsentMode.NONE)
    assert result["confirmed"] is False
    assert po.peek_pending_offer() is not None
