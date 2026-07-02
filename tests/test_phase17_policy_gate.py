"""Phase 17 — capability policy gate at the autonomous execution boundary."""
import pytest

import action_engine as ae


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    # Neutralise goal-store side effects; capture whether execute_action ran.
    ran = {"n": 0}
    monkeypatch.setattr(ae, "update_goal", lambda *a, **k: None)
    monkeypatch.setattr(ae, "log_execution", lambda *a, **k: None)
    monkeypatch.setattr(ae, "execute_action",
                        lambda at, p: ran.__setitem__("n", ran["n"] + 1) or
                        {"success": True, "result": "ran"})
    yield ran


def test_red_action_blocked_when_enabled(monkeypatch, _stub):
    monkeypatch.setenv("ULTRON_PHASE17_ENABLED", "1")
    task = {"tool": "delete_folder", "params": {"path": "/tmp/x"},
            "human_confirmed": True}          # even confirmed, RED stays blocked
    r = ae.execute_goal_step("g1", task)
    assert r["success"] is False
    assert "capability policy" in r["error"]
    assert _stub["n"] == 0                     # execute_action never called


def test_amber_needs_confirmation(monkeypatch, _stub):
    monkeypatch.setenv("ULTRON_PHASE17_ENABLED", "1")
    task = {"tool": "file_write", "params": {"path": "/tmp/x", "content": "y"}}
    r = ae.execute_goal_step("g1", task)
    assert r["success"] is False
    assert "needs human_confirmed" in r["error"]
    assert _stub["n"] == 0


def test_amber_allowed_when_confirmed(monkeypatch, _stub):
    monkeypatch.setenv("ULTRON_PHASE17_ENABLED", "1")
    task = {"tool": "file_write", "params": {"path": "/tmp/x", "content": "y"},
            "human_confirmed": True}
    r = ae.execute_goal_step("g1", task)
    assert r["success"] is True
    assert _stub["n"] == 1


def test_green_runs_freely(monkeypatch, _stub):
    monkeypatch.setenv("ULTRON_PHASE17_ENABLED", "1")
    task = {"tool": "note_create", "params": {"content": "hi"}}
    r = ae.execute_goal_step("g1", task)
    assert r["success"] is True
    assert _stub["n"] == 1


def test_flag_off_is_unchanged(monkeypatch, _stub):
    monkeypatch.setenv("ULTRON_PHASE17_ENABLED", "0")
    task = {"tool": "delete_folder", "params": {"path": "/tmp/x"}}
    r = ae.execute_goal_step("g1", task)
    assert r["success"] is True                # policy not consulted
    assert _stub["n"] == 1
