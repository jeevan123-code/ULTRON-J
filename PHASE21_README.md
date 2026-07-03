# Phase 21 — Multi-Agent Swarm Coordinator (Tier 3)

"Ultron isn't one program." `chain_executor` runs ONE plan sequentially; this
coordinator fans several specialist SUB-AGENTS out in PARALLEL and merges them.

## `swarm_coordinator.py`
- `SubAgent(name, role, plan)` — a specialist + its ExecutionPlan.
- `dispatch(agents, max_workers, per_agent_timeout)` — runs every agent's plan
  concurrently (ThreadPoolExecutor) through `chain_executor` (mockable seam).
  One agent's failure or timeout is isolated; never aborts the others.
- `summarize()` / `run_swarm()` — merge into a single report
  (total / succeeded / failed / by_agent).

## Tests (6)
`tests/test_swarm_coordinator.py` — fan-out + merge, failure isolation,
step-error detection, per-agent timeout, real parallelism (3×0.3s < 0.7s),
empty input.
