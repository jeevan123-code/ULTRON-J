# Phase 8 — Multi-Step Planning

Status: SHIPPED on branch `phase8-multi-step-planning`.

## What Phase 8 Builds

Every previous phase had a single-action `ExecutionPlan`:
- `phase2_executor` runs `plan.steps[0]` if it's a research step.
- `takeover_executor` runs `plan.steps[0]` if it's a takeover step.
- `multi_device_coordinator.run` iterates scenario steps but those are
  per-device, not heterogenous actions.

Nothing chained heterogenous actions together. JARVIS's value isn't that
he runs *one* action; it's that he runs *the right sequence*:

> "Sir, AAPL just halted — researched the cause, pushed a brief to your
>  phone, and silenced the front-door bell so you can read it."

That's three different action types in one decision. Phase 8 makes that
shape possible.

## The chain executor

```python
from chain_executor import execute_chain
from intent_types import ExecutionPlan

plan = ExecutionPlan(
    steps=[
        {"action": "research", "args": {"topic": "AAPL halt cause"}},
        {"action": "alert", "args": {
            "message": "AAPL halt — research: {{prev.summary}}",
            "priority": "high",
        }},
        {"action": "scenario", "args": {"name": "get_ready_for_call"}},
    ],
    pre_checks=[], rationale="market event",
)

results = execute_chain(plan)
# [{"ok": True, "action": "research", "result": {...}},
#  {"ok": True, "action": "alert",    "result": {...}},
#  {"ok": True, "action": "scenario", "result": {...}}]
```

### Inter-step references

A step's args support `{{prev.<key>}}` placeholders that interpolate
values from the previous step's `result` dict. Above, `{{prev.summary}}`
fills in the research summary into the alert message.

### Failure policy

Default: the chain stops at the first failed step. A step can opt out
with `continue_on_failure: True` (mirrors Phase 6's defensive style):

```python
{"action": "optional_telegram", "args": {...}, "continue_on_failure": True}
```

### Supported action types

| Action | Routes to | Step args |
|---|---|---|
| `research` | `phase2_executor.execute` | `{topic: str}` |
| `takeover` | `takeover_executor.execute` | `{type_text|keys|press_key}` |
| `alert` | `mobile_bridge.alert` | `{message: str, priority: str}` |
| `announce` | `voice_engine.tts` | `{text: str}` |
| `scenario` | `multi_device_coordinator.run` (by name) | `{name: str}` |
| `briefing` | `briefing_builder.compose` + `briefing_delivery.deliver` | `{channels: List[str]}` |

Every dispatcher is a small `_dispatch_*` indirection at module level,
so tests stub by `monkeypatch.setattr(chain_executor, "_dispatch_…", …)`.

## Modules

| File | Tests | Purpose |
|---|---:|---|
| `chain_executor.py` | 10 | `execute_chain(plan)` — multi-action plan runner |

**10 new tests**, zero regression on the 1055-test Phase 7 baseline.

## How to enable

No flag. `chain_executor` is a library — call it from anywhere that
already builds an `ExecutionPlan`. Existing single-step callers
(`phase2_executor`, `takeover_executor`) are untouched.

Typical wiring (future, not in this phase): a higher-level intent parser
builds a multi-action plan from a single user utterance ("research X
then alert me when done") and feeds it through `chain_executor`.

## How to test

```bash
.venv/bin/python -m pytest tests/test_chain_executor.py -v
```

## What's next

- **Plan builder** — a function that turns a user utterance into a chained
  `ExecutionPlan` (LLM-assisted or rule-based). Currently chain plans
  must be hand-built; an autoplanner closes that loop.
- **Conditional branching** — a step can specify `if_prev_ok` /
  `if_prev_failed` to route around or recover from upstream failures.
- **Vision** — webcam awareness so plans can include "look at the door"
  or "check what's on screen" as primitive steps.
