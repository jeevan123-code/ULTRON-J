"""Tests for Phase 11 — conditional steps in chain_executor."""
from unittest.mock import MagicMock

import pytest

import chain_executor
from intent_types import ExecutionPlan


def _plan(*steps):
    return ExecutionPlan(steps=list(steps), pre_checks=[], rationale="test")


def test_if_prev_ok_true_runs_when_prev_succeeded(monkeypatch):
    research = MagicMock(return_value={"executed": True})
    alert = MagicMock(return_value={"sent": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", research)
    monkeypatch.setattr(chain_executor, "_dispatch_alert", lambda m, p: alert(m, p))

    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "x"}},
        {"action": "alert", "args": {"message": "ok"}, "if_prev_ok": True},
    ))
    assert len(out) == 2
    assert out[1]["ok"] is True
    alert.assert_called_once()


def test_if_prev_ok_skipped_when_prev_failed(monkeypatch):
    # First step (research) succeeds because dispatcher returns executed=True
    research = MagicMock(return_value={"executed": False, "reason": "missing_topic"})
    alert = MagicMock()
    monkeypatch.setattr(chain_executor, "_dispatch_research", research)
    monkeypatch.setattr(chain_executor, "_dispatch_alert", lambda m, p: alert(m, p))

    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "x"},
         "continue_on_failure": True},
        {"action": "alert", "args": {"message": "ok"}, "if_prev_ok": True},
    ))
    # Two records: research (ok=False), alert (skipped because prev not ok)
    assert len(out) == 2
    assert out[0]["ok"] is False
    assert out[1].get("skipped") is True
    alert.assert_not_called()


def test_if_prev_failed_runs_when_prev_failed(monkeypatch):
    """A recovery step fires only when the prior step failed."""
    research = MagicMock(return_value={"executed": False, "reason": "engine_error"})
    alert = MagicMock(return_value={"sent": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", research)
    monkeypatch.setattr(chain_executor, "_dispatch_alert", lambda m, p: alert(m, p))

    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "x"},
         "continue_on_failure": True},
        {"action": "alert", "args": {"message": "Research failed; manual lookup needed."},
         "if_prev_failed": True},
    ))
    assert len(out) == 2
    assert out[1]["ok"] is True
    alert.assert_called_once()


def test_if_prev_failed_skipped_when_prev_succeeded(monkeypatch):
    research = MagicMock(return_value={"executed": True})
    alert = MagicMock()
    monkeypatch.setattr(chain_executor, "_dispatch_research", research)
    monkeypatch.setattr(chain_executor, "_dispatch_alert", lambda m, p: alert(m, p))

    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "x"}},
        {"action": "alert", "args": {"message": "recovery"},
         "if_prev_failed": True},
    ))
    assert out[0]["ok"] is True
    assert out[1].get("skipped") is True
    alert.assert_not_called()


def test_first_step_with_if_prev_ok_runs_by_default(monkeypatch):
    """No prior step exists. if_prev_ok: True is satisfied vacuously."""
    research = MagicMock(return_value={"executed": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", research)
    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "x"}, "if_prev_ok": True},
    ))
    assert out[0]["ok"] is True
    research.assert_called_once()


def test_first_step_with_if_prev_failed_skipped(monkeypatch):
    """No prior failure — recovery step is skipped on step 0."""
    research = MagicMock()
    monkeypatch.setattr(chain_executor, "_dispatch_research", research)
    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "x"}, "if_prev_failed": True},
    ))
    assert out[0].get("skipped") is True
    research.assert_not_called()


def test_skipped_step_does_not_reset_prev(monkeypatch):
    """Step skipped by condition should leave prev_result untouched for the next step."""
    research = MagicMock(return_value={"executed": True, "summary": "AAPL up"})
    alert = MagicMock(return_value={"sent": True})
    monkeypatch.setattr(chain_executor, "_dispatch_research", research)
    captured = {}
    def _capture_alert(message, priority):
        captured["msg"] = message
        return {"sent": True}
    monkeypatch.setattr(chain_executor, "_dispatch_alert", _capture_alert)

    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "AAPL"}},
        # This step gets skipped because prev (research) succeeded
        {"action": "alert", "args": {"message": "fallback"},
         "if_prev_failed": True},
        # This step should still see the research summary via {{prev.summary}}
        {"action": "alert", "args": {"message": "Result: {{prev.summary}}"}},
    ))
    assert out[1].get("skipped") is True
    assert out[2]["ok"] is True
    assert "AAPL up" in captured["msg"]


def test_mutually_exclusive_branches(monkeypatch):
    """Realistic shape: research X; either announce success OR alert failure."""
    research = MagicMock(return_value={"executed": False, "reason": "rate_limited"})
    captured = {}
    def _announce(text):
        captured["announce"] = text
        return (b"a", "edge")
    def _alert(message, priority):
        captured["alert"] = message
        return {"sent": True}
    monkeypatch.setattr(chain_executor, "_dispatch_research", research)
    monkeypatch.setattr(chain_executor, "_dispatch_announce", _announce)
    monkeypatch.setattr(chain_executor, "_dispatch_alert", _alert)

    out = chain_executor.execute_chain(_plan(
        {"action": "research", "args": {"topic": "x"},
         "continue_on_failure": True},
        {"action": "announce", "args": {"text": "Done."},
         "if_prev_ok": True},
        {"action": "alert", "args": {"message": "Research failed."},
         "if_prev_failed": True},
    ))
    assert out[1].get("skipped") is True   # success branch skipped
    assert out[2]["ok"] is True              # failure branch fired
    assert "announce" not in captured
    assert "alert" in captured
