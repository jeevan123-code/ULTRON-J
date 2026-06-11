"""Tests for the 'look' action added to chain_executor in Phase 9."""
from unittest.mock import MagicMock

import pytest

import chain_executor
import vision_capture
import vision_perception
from intent_types import ExecutionPlan
from vision_types import VisionFrame, VisionObservation


def _plan(*steps):
    return ExecutionPlan(steps=list(steps), pre_checks=[], rationale="test")


def test_look_action_runs_capture_and_perception(monkeypatch):
    fake_frame = VisionFrame(ts=1.0, width=640, height=480, raw=b"x")
    fake_obs = VisionObservation(ts=1.0, faces=1, person_present=True)
    monkeypatch.setattr(vision_capture, "get_latest_frame", lambda: fake_frame)
    monkeypatch.setattr(vision_perception, "observe", lambda f: fake_obs)
    out = chain_executor.execute_chain(_plan({"action": "look"}))
    assert out[0]["ok"] is True
    assert out[0]["result"]["person_present"] is True
    assert out[0]["result"]["faces"] == 1


def test_look_action_returns_failure_when_no_camera(monkeypatch):
    monkeypatch.setattr(vision_capture, "get_latest_frame", lambda: None)
    out = chain_executor.execute_chain(_plan({"action": "look"}))
    assert out[0]["ok"] is False
    assert "no_frame" in out[0]["error"] or "no frame" in out[0]["error"].lower()


def test_look_result_flows_into_next_step_via_prev(monkeypatch):
    fake_frame = VisionFrame(ts=1.0, width=640, height=480, raw=b"x")
    fake_obs = VisionObservation(ts=1.0, faces=2, person_present=True)
    monkeypatch.setattr(vision_capture, "get_latest_frame", lambda: fake_frame)
    monkeypatch.setattr(vision_perception, "observe", lambda f: fake_obs)

    captured = {}
    def _fake_alert(message, priority):
        captured["msg"] = message
        return {"sent": True}
    monkeypatch.setattr(chain_executor, "_dispatch_alert", _fake_alert)

    out = chain_executor.execute_chain(_plan(
        {"action": "look"},
        {"action": "alert", "args": {"message": "I see {{prev.faces}} people"}},
    ))
    assert all(r["ok"] for r in out)
    assert "I see 2 people" in captured["msg"]
