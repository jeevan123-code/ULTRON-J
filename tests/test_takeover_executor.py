"""Tests for takeover_executor — thin wrapper around computer_control."""
from unittest.mock import patch, MagicMock

import pytest

import takeover_executor as te
from intent_types import ExecutionPlan


def _plan(args: dict) -> ExecutionPlan:
    return ExecutionPlan(
        steps=[{"action": "takeover", "args": args}],
        pre_checks=[],
        rationale="test",
    )


def test_empty_plan_returns_not_executed():
    result = te.execute(ExecutionPlan(steps=[], pre_checks=[], rationale=""))
    assert result["executed"] is False
    assert result["reason"] == "empty_plan"


def test_non_takeover_action_returns_not_executed():
    plan = ExecutionPlan(
        steps=[{"action": "research", "args": {"topic": "x"}}],
        pre_checks=[], rationale="",
    )
    result = te.execute(plan)
    assert result["executed"] is False
    assert result["reason"] == "not_takeover"


def test_type_text_dispatches_to_computer_control(monkeypatch):
    captured = {}

    def fake_type_text(text, **kw):
        captured["text"] = text
        return {"success": True, "chars_typed": len(text)}

    monkeypatch.setattr(te, "_type_text", fake_type_text)
    result = te.execute(_plan({"type_text": "hello world"}))
    assert result["executed"] is True
    assert captured["text"] == "hello world"


def test_keys_dispatches_to_hotkey(monkeypatch):
    captured = {}

    def fake_hotkey(*keys):
        captured["keys"] = list(keys)
        return {"success": True, "keys": list(keys)}

    monkeypatch.setattr(te, "_hotkey", fake_hotkey)
    result = te.execute(_plan({"keys": ["ctrl", "shift", "p"]}))
    assert result["executed"] is True
    assert captured["keys"] == ["ctrl", "shift", "p"]


def test_exception_in_dispatch_is_caught(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("pyautogui exploded")

    monkeypatch.setattr(te, "_type_text", boom)
    result = te.execute(_plan({"type_text": "x"}))
    assert result["executed"] is False
    assert "error" in result


def test_unknown_args_returns_malformed():
    result = te.execute(_plan({"mystery_param": "x"}))
    assert result["executed"] is False
    assert result["reason"] == "malformed_plan"
