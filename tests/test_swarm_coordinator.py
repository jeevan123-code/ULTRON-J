"""Tests for swarm_coordinator — parallel sub-agent fan-out/merge."""
import time

import pytest

import swarm_coordinator as sc
from swarm_coordinator import SubAgent, dispatch, summarize, run_swarm


def _agents():
    return [
        SubAgent("researcher", "research", plan="P1"),
        SubAgent("coder", "code", plan="P2"),
        SubAgent("monitor", "watch", plan="P3"),
    ]


def test_all_agents_run_and_merge(monkeypatch):
    monkeypatch.setattr(sc, "_execute", lambda plan: [{"ok": True, "result": plan}])
    report = run_swarm(_agents())
    assert report["total"] == 3
    assert report["succeeded"] == 3
    assert set(report["succeeded_agents"]) == {"researcher", "coder", "monitor"}


def test_one_agent_failure_is_isolated(monkeypatch):
    def _exec(plan):
        if plan == "P2":
            raise RuntimeError("coder blew up")
        return [{"ok": True}]
    monkeypatch.setattr(sc, "_execute", _exec)
    report = run_swarm(_agents())
    assert report["succeeded"] == 2
    assert report["failed_agents"] == ["coder"]
    assert "coder blew up" in report["by_agent"]["coder"]["error"]


def test_step_error_marks_agent_failed(monkeypatch):
    monkeypatch.setattr(sc, "_execute",
                        lambda plan: [{"error": "step failed"}] if plan == "P3"
                        else [{"ok": True}])
    report = run_swarm(_agents())
    assert "monitor" in report["failed_agents"]


def test_timeout_isolated(monkeypatch):
    def _slow(plan):
        if plan == "P1":
            time.sleep(2)
        return [{"ok": True}]
    monkeypatch.setattr(sc, "_execute", _slow)
    report = run_swarm(_agents(), per_agent_timeout=0.2)
    assert report["by_agent"]["researcher"]["error"] == "timed_out"
    assert "coder" in report["succeeded_agents"]


def test_runs_in_parallel(monkeypatch):
    # 3 agents each sleeping 0.3s should finish in well under 0.9s if parallel.
    monkeypatch.setattr(sc, "_execute", lambda plan: time.sleep(0.3) or [{"ok": True}])
    t0 = time.time()
    dispatch(_agents(), max_workers=3)
    assert time.time() - t0 < 0.7


def test_empty_agents():
    assert dispatch([]) == {}
    assert summarize({})["total"] == 0
