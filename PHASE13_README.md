# Phase 13 — Strict Validation

Status: SHIPPED on branch `phase13-strict-validation`.

## What Phase 13 Builds

Phase 12 gave us `plan_validator`. It was a library — useful only to
callers who remembered to call it. Phase 13 wires it as a guardrail on
the actual execution boundary:

```python
chain_executor.execute_chain(plan, strict_validation=True)
```

With `strict_validation=True`, `execute_chain` runs the validator first.
If any issue has severity `error`, no step executes and a single result
returns:

```python
[{
    "ok": False,
    "skipped": True,
    "reason": "validation_failed",
    "validation_issues": [
        {"severity": "error", "step_index": 0,
         "message": "action 'researhc' is unknown"},
    ],
}]
```

Warnings do NOT block. The default is `strict_validation=False` — fully
backward compatible with every existing Phase 8 / Phase 11 chain.

## The voice_engine hook is now strict

The Phase 10b hook inside `voice_engine.parse_voice_command` now passes
`strict_validation=True`. So a typo in `plan_builder`'s pattern table,
a future plan source, or any malformed `ExecutionPlan` reaching the
voice surface gets rejected *before* it triggers TTS, Telegram alerts,
or computer_control.

That closes the last gap in the pipeline:

```
utterance
    │
    ▼
plan_builder.build_from_utterance
    │
    ▼
chain_executor.execute_chain(strict_validation=True)
    │
    ├── plan_validator.validate ── errors? short-circuit
    │
    └── for each step:
            ├── if_prev_ok / if_prev_failed gating
            ├── {{prev.X}} interpolation
            └── dispatch (research, takeover, look, scenario, alert, announce, briefing)
```

Every transition is now defended.

## Defensive design

- A crash inside `plan_validator.validate` is itself caught. The chain
  still runs. Making validation less reliable than no validation would
  be the wrong tradeoff — Phase 13 strictly *adds* a guardrail, never
  weakens the existing path.
- Strict mode is opt-in. Existing callers (Phase 7's `mind_tick`, the
  Phase 6 cron scheduler's eventual `execute_chain` path, etc.) keep
  their original semantics unless they explicitly opt in.

## Modules

| File | Tests | Purpose |
|---|---:|---|
| `chain_executor.py` (extended) | 6 | new `strict_validation` kwarg + pre-flight validate |
| `voice_engine.py` (modified) | 2 | Phase 10 hook now passes `strict_validation=True` |

**8 new tests**, zero regression on the 1125-test Phase 12 baseline.
All 30 existing voice integration tests preserved.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_phase13_strict_validation.py \
    tests/test_phase13_voice_strict.py -v
```

## What's next

- Opt-in strict mode on `mind_tick`'s briefing dispatch and on the
  Phase 6 scheduler tick — those are background paths where catching
  a misconfigured cron schedule early would save a lot of confused
  logs.
- A `strict_validation` env var so deployments can flip the default
  without code changes.
- LLM fallback for `plan_builder` (the real next big build) — strict
  validation becomes load-bearing once an LLM is producing plans
  because hallucinated action types and missing args are exactly the
  failure modes Phase 12 catches.
