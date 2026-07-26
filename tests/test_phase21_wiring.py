"""Phase 21 wiring — the swarm coordinator hangs off chain_executor.

chain_executor runs ONE plan sequentially. execute_parallel() is the seam that
fans several independent plans out across sub-agents and merges the results.

The flag controls PARALLELISM, not existence: with ULTRON_PHASE21_ENABLED unset
the same call still runs every plan, just sequentially. A fan-out that silently
does nothing when the flag is off would be the orphan problem again.
"""
import pytest

import chain_executor
import swarm_coordinator as sc
from swarm_coordinator import SubAgent


@pytest.fixture
def plans(monkeypatch):
    """Replace real chain execution with a recorder."""
    ran = []

    def _fake_execute(plan):
        ran.append(plan)
        if plan == "BAD":
            return [{"ok": False, "error": "nope"}]
        return [{"ok": True, "result": plan}]

    monkeypatch.setattr(sc, "_execute", _fake_execute)
    monkeypatch.setattr(chain_executor, "execute_chain", _fake_execute)
    return ran


def _agents():
    return [SubAgent("researcher", "research", "P1"),
            SubAgent("coder", "code", "P2")]


def test_parallel_path_runs_every_agent(monkeypatch, plans):
    monkeypatch.setenv("ULTRON_PHASE21_ENABLED", "1")
    report = chain_executor.execute_parallel(_agents())
    assert report["total"] == 2
    assert report["succeeded"] == 2
    assert sorted(plans) == ["P1", "P2"]


def test_sequential_fallback_when_flag_off(monkeypatch, plans):
    monkeypatch.delenv("ULTRON_PHASE21_ENABLED", raising=False)
    report = chain_executor.execute_parallel(_agents())
    assert report["total"] == 2
    assert report["succeeded"] == 2
    assert plans == ["P1", "P2"], "sequential path must preserve order"


def test_both_paths_return_the_same_shape(monkeypatch, plans):
    monkeypatch.setenv("ULTRON_PHASE21_ENABLED", "1")
    par = chain_executor.execute_parallel(_agents())
    monkeypatch.delenv("ULTRON_PHASE21_ENABLED", raising=False)
    seq = chain_executor.execute_parallel(_agents())
    assert set(par) == set(seq)
    assert set(par["by_agent"]) == set(seq["by_agent"]) == {"researcher", "coder"}


def test_one_failing_agent_does_not_sink_the_others(monkeypatch, plans):
    monkeypatch.setenv("ULTRON_PHASE21_ENABLED", "1")
    agents = [SubAgent("good", "r", "P1"), SubAgent("bad", "c", "BAD")]
    report = chain_executor.execute_parallel(agents)
    assert report["succeeded_agents"] == ["good"]
    assert report["failed_agents"] == ["bad"]


def test_failure_isolation_also_holds_sequentially(monkeypatch, plans):
    monkeypatch.delenv("ULTRON_PHASE21_ENABLED", raising=False)
    agents = [SubAgent("bad", "c", "BAD"), SubAgent("good", "r", "P1")]
    report = chain_executor.execute_parallel(agents)
    assert report["succeeded_agents"] == ["good"]
    assert "P1" in plans, "a failing agent must not stop later agents"


def test_empty_agent_list_is_an_empty_report(monkeypatch, plans):
    monkeypatch.setenv("ULTRON_PHASE21_ENABLED", "1")
    report = chain_executor.execute_parallel([])
    assert report["total"] == 0
    assert plans == []


def test_raising_agent_is_isolated_sequentially(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE21_ENABLED", raising=False)

    def _boom(plan):
        if plan == "BOOM":
            raise RuntimeError("agent exploded")
        return [{"ok": True}]

    monkeypatch.setattr(chain_executor, "execute_chain", _boom)
    report = chain_executor.execute_parallel(
        [SubAgent("boom", "r", "BOOM"), SubAgent("fine", "r", "OK")])
    assert report["failed_agents"] == ["boom"]
    assert report["succeeded_agents"] == ["fine"]
