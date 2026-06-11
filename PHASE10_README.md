# Phase 10 — Plan Builder

Status: SHIPPED on branch `phase10-plan-builder`.

## What Phase 10 Builds

Phase 8 introduced multi-step `ExecutionPlan` chains. Phase 9 added
`look` as a primitive. Until now, building those chained plans required
hand-writing the steps in Python. Phase 10 closes the loop:

```python
from plan_builder import build_from_utterance
from chain_executor import execute_chain

plan = build_from_utterance("look at the door and tell me who's there")
# ExecutionPlan(steps=[
#   {"action": "look"},
#   {"action": "announce", "args": {
#       "text": "Sir, I see {{prev.faces}} person(s) in front of the camera.",
#   }, "continue_on_failure": True},
# ], ...)

execute_chain(plan)
# -> webcam grab, perception, voice announcement using face count
```

One utterance becomes one chain. That is the JARVIS-shape:
**user says one thing, multiple subsystems coordinate as a single
intent.**

## Pattern table

| Utterance shape | Resulting chain |
|---|---|
| `research X and tell/alert/notify me` | `[research, alert]` |
| `research X and read/say/announce` | `[research, announce]` |
| `research X` | `[research]` |
| `look at the door` / `who's there` | `[look, announce]` |
| `brief me [now]` | `[briefing(channels=[voice, telegram])]` |
| `house party protocol` / `lockdown mode` | `[scenario(house_party)]` |
| `bedtime` / `good night` | `[scenario(bedtime)]` |
| `get me ready` / `prep for the call` | `[scenario(get_ready_for_call)]` |

First-match-wins. Specific patterns precede general ones so
`"research X and tell me"` never falls into the bare `research X` rule.

## Why rule-based, not LLM

Deterministic, fast, unit-testable, and safe (no hallucinated action
types). When a future LLM tier is added, it can chain *after*
`plan_builder`: try patterns first; if `plan.steps == []`, fall through
to a model. That way 90% of common phrasings stay zero-latency and only
genuinely novel utterances pay the network round-trip.

## Modules

| File | Tests | Purpose |
|---|---:|---|
| `plan_builder.py` | 11 | `build_from_utterance(text) -> ExecutionPlan` |

**11 new tests**, zero regression on the 1085-test Phase 9 baseline.

## How to enable

No flag. `plan_builder` is a library — pass utterances to it from
wherever you already receive them (typically `voice_engine.parse_voice_command`
or an HTTP endpoint).

Typical wiring (deferred to a future phase to keep voice_engine surgical):

```python
import plan_builder, chain_executor
plan = plan_builder.build_from_utterance(transcript)
if plan.steps:
    chain_executor.execute_chain(plan)
    return None  # short-circuit voice_engine fast-path
```

## How to test

```bash
.venv/bin/python -m pytest tests/test_plan_builder.py -v
```

## What's next

- LLM fallback for `plan.steps == []` so novel utterances become plans
  too (still gated; not every utterance should be a plan).
- Plan validator that catches obviously bad chains (e.g., `announce`
  with `{{prev.X}}` where prior step had no such field) before they hit
  `execute_chain`.
- Voice-engine hook that calls `plan_builder` + `chain_executor` when
  Phase 10 flag is on, behind the existing fast-path.
