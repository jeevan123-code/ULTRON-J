"""Phase 17 wiring — the capability gate in action_engine.execute_goal_step.

The gate is only a gate if it refuses when it cannot run. These cover the
fault path: a policy module that raises must DENY the action, never fall
through to execute_action.
"""
import pytest

import action_engine
import capability_policy


@pytest.fixture(autouse=True)
def _reset():
    capability_policy._reset_for_test()
    yield
    capability_policy._reset_for_test()


def _spy_execute_action(monkeypatch):
    """Replace execute_action with a recorder so we can prove it never ran."""
    calls = []

    def _spy(action_type, params):
        calls.append((action_type, params))
        return {"success": True, "result": "should-not-happen"}

    monkeypatch.setattr(action_engine, "execute_action", _spy)
    return calls


def test_policy_error_refuses_instead_of_falling_through(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE17_ENABLED", "1")
    monkeypatch.setattr(
        capability_policy, "enforce",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("policy exploded")))
    calls = _spy_execute_action(monkeypatch)

    result = action_engine.execute_goal_step("fake_goal_id", {
        "id": "s0", "tool": "file_read", "description": "read something",
        "params": {"path": "/tmp/x"},
    })

    assert result["success"] is False
    assert "capability policy" in result["error"]
    assert calls == [], "action executed despite the gate failing"


def test_policy_error_refuses_even_when_human_confirmed(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE17_ENABLED", "1")
    monkeypatch.setattr(
        capability_policy, "enforce",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("policy exploded")))
    calls = _spy_execute_action(monkeypatch)

    result = action_engine.execute_goal_step("fake_goal_id", {
        "id": "s0", "tool": "file_write", "description": "write something",
        "params": {"path": "/tmp/x", "content": "y"},
        "human_confirmed": True,
    })

    assert result["success"] is False
    assert calls == []


def test_gate_disabled_is_unaffected(monkeypatch):
    # Flag OFF must keep pre-Phase-17 behaviour exactly: no gate, no refusal.
    monkeypatch.delenv("ULTRON_PHASE17_ENABLED", raising=False)
    monkeypatch.setattr(
        capability_policy, "enforce",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("must not be called")))
    calls = _spy_execute_action(monkeypatch)

    action_engine.execute_goal_step("fake_goal_id", {
        "id": "s0", "tool": "file_read", "description": "read something",
        "params": {"path": "/tmp/x"},
    })

    assert calls, "with the flag off the action should have run"


def test_healthy_gate_still_blocks_red_and_allows_green(monkeypatch):
    # Regression guard: the fault path must not disturb normal enforcement.
    monkeypatch.setenv("ULTRON_PHASE17_ENABLED", "1")
    calls = _spy_execute_action(monkeypatch)

    blocked = action_engine.execute_goal_step("fake_goal_id", {
        "id": "s0", "tool": "delete_file", "description": "nuke it",
        "params": {"path": "/tmp/x"}, "human_confirmed": True,
    })
    assert blocked["success"] is False
    assert "red" in blocked["error"]
    assert calls == []

    action_engine.execute_goal_step("fake_goal_id", {
        "id": "s1", "tool": "file_read", "description": "read it",
        "params": {"path": "/tmp/x"},
    })
    assert calls, "a GREEN action must still be allowed through"
