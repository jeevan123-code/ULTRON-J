# Phase 11 — Conditional Chains

Status: SHIPPED on branch `phase11-conditional-chains`.

## What Phase 11 Builds

Phase 8 introduced chains. Phase 11 makes them **branch**.

A step can carry one of two new flags:

| Flag | Step runs when… |
|---|---|
| `if_prev_ok: True` | the previous executed step succeeded (vacuously true on step 0) |
| `if_prev_failed: True` | the previous executed step failed (skipped on step 0) |

Skipped steps are recorded with `{"ok": False, "skipped": True,
"reason": "condition_not_met"}` so the chain stays fully auditable.
Skipped steps are **neutral** for downstream conditions — they don't
flip `prev_ok` and they don't reset `prev_result`. The next step still
sees the most recent step that actually executed.

## Why this matters

Before Phase 11, chains were linear. Failure was binary: stop, or
`continue_on_failure` and keep going. There was no way to express:

> "Research the AAPL halt. If it works, announce the summary. If it
>  doesn't, alert me that I'll need to look manually."

Now there is:

```python
plan = ExecutionPlan(
    steps=[
        {"action": "research", "args": {"topic": "AAPL halt cause"},
         "continue_on_failure": True},
        {"action": "announce", "args": {"text": "Sir, here's what I found: {{prev.summary}}"},
         "if_prev_ok": True},
        {"action": "alert", "args": {"message": "Research failed — manual lookup needed.",
                                       "priority": "high"},
         "if_prev_failed": True},
    ],
    pre_checks=[], rationale="branching example",
)
execute_chain(plan)
```

That's the recovery / branching primitive ULTRON was missing — JARVIS-shape
reasoning in three lines per branch.

## Modules

| File | Tests | Purpose |
|---|---:|---|
| `chain_executor.py` (extended) | 8 | `_should_skip(step, prev_ran, prev_ok)` + branch logic in `execute_chain` |

**8 new tests**, zero regression on the 1101-test Phase 10b baseline.
Phase 8 (10) + Phase 9 (3) chain_executor tests preserved.

## How to enable

No flag — built into `chain_executor.execute_chain`. Existing chains
without `if_prev_ok` / `if_prev_failed` flags behave exactly as before.

## Composition with existing flags

| Combination | Behavior |
|---|---|
| `if_prev_ok` only | runs iff prev succeeded |
| `if_prev_failed` only | runs iff prev failed (recovery) |
| `continue_on_failure` only | runs always; on failure, chain continues |
| `continue_on_failure` + `if_prev_failed` | recovery step; if it ALSO fails, chain continues to next |
| neither | runs always; on failure, chain stops (default) |

Both new flags can technically appear together on one step — it would
then run only when prev *both* succeeded AND failed, i.e., never. The
executor doesn't reject this, but `plan_builder` won't produce it.

## How to test

```bash
.venv/bin/python -m pytest tests/test_phase11_conditional_chains.py -v
```

## What's next

- A pattern in `plan_builder` that emits a conditional fallback for any
  research-style chain (e.g., "research X and tell me" auto-includes a
  recovery alert step on failure).
- `if_prev_skipped` flag — "run only if the prior step was skipped"
  — gives true if/elif/else triads. Holding off for now until real
  use-cases demand it.
- A small plan validator that catches obviously-nonsensical combinations
  (e.g., both `if_prev_ok` and `if_prev_failed` on the same step).
