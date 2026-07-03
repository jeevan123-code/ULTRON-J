"""Phase 21 — multi-agent swarm coordinator (Tier 3).

"Ultron isn't one program." chain_executor runs ONE plan sequentially; this
coordinator fans several specialist SUB-AGENTS (researcher, coder, monitor, ...)
out in PARALLEL, isolates their failures, enforces a per-agent timeout, and
MERGES their results into one report.

Each sub-agent is just a name + role + an ExecutionPlan; the coordinator runs
each plan through chain_executor (a mockable seam) on a worker thread.
"""
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeout
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SubAgent:
    name: str
    role: str
    plan: Any                        # ExecutionPlan (or anything _execute accepts)


def _execute(plan: Any) -> List[Dict[str, Any]]:
    """Run one sub-agent's plan. Seam over chain_executor (mocked in tests)."""
    from chain_executor import execute_chain
    return execute_chain(plan)


def _results_ok(results: List[Dict[str, Any]]) -> bool:
    """An agent succeeded if no step reported an error / failure."""
    if not isinstance(results, list):
        return False
    for r in results:
        if not isinstance(r, dict):
            continue
        if r.get("error"):
            return False
        if r.get("ok") is False or r.get("success") is False:
            return False
    return True


def dispatch(agents: List[SubAgent], max_workers: int = 4,
             per_agent_timeout: float = 60.0) -> Dict[str, Dict[str, Any]]:
    """Run every sub-agent in parallel. Returns {name: {ok, role, results|error}}.

    One agent's failure or timeout never affects the others.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not agents:
        return out
    workers = max(1, min(max_workers, len(agents)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(_execute, a.plan): a for a in agents}
        for future, agent in future_map.items():
            entry: Dict[str, Any] = {"role": agent.role}
            try:
                results = future.result(timeout=per_agent_timeout)
                entry["results"] = results
                entry["ok"] = _results_ok(results)
            except _FTimeout:
                entry["ok"] = False
                entry["error"] = "timed_out"
            except Exception as e:
                entry["ok"] = False
                entry["error"] = repr(e)
            out[agent.name] = entry
    return out


def summarize(dispatch_result: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Roll a dispatch result up into a single report."""
    total = len(dispatch_result)
    succeeded = [n for n, v in dispatch_result.items() if v.get("ok")]
    failed = [n for n, v in dispatch_result.items() if not v.get("ok")]
    return {
        "total": total,
        "succeeded": len(succeeded),
        "failed": len(failed),
        "succeeded_agents": succeeded,
        "failed_agents": failed,
        "by_agent": dispatch_result,
    }


def run_swarm(agents: List[SubAgent], **kw) -> Dict[str, Any]:
    """Convenience: dispatch + summarize."""
    return summarize(dispatch(agents, **kw))
