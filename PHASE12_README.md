# Phase 12 — Plan Validator

Status: SHIPPED on branch `phase12-plan-validator`.

## What Phase 12 Builds

Phase 8/9/10/11 produce richer and richer `ExecutionPlan` shapes. A
typo in an action name, a missing required arg, or a mutually-exclusive
flag combo would only surface at runtime — usually as a silent failure
inside `chain_executor`. Phase 12 catches those statically:

```python
from plan_validator import validate, SEVERITY_ERROR

plan = ExecutionPlan(steps=[
    {"action": "researhc", "args": {"topic": "AAPL"}},  # typo!
    {"action": "alert", "args": {}},                     # missing message!
], pre_checks=[], rationale="")

issues = validate(plan)
for i in issues:
    print(f"  [{i.severity}] step {i.step_index}: {i.message}")
# [error] step 0: unknown action 'researhc'
# [error] step 1: action 'alert' missing required arg 'message'

errors = [i for i in issues if i.severity == SEVERITY_ERROR]
if errors:
    abort("plan_validator rejected the plan")
```

The validator never raises; it returns a list of `ValidationIssue`
records (`{severity, step_index, message}`). Callers decide whether to
surface, log, or block.

## Conservative scope

Phase 12 only catches issues that are *always* wrong regardless of
runtime state:

| Check | Severity |
|---|---|
| empty `steps` list | warning |
| missing `action` field | error |
| unknown action name | error |
| missing required arg per action | error |
| `if_prev_ok` AND `if_prev_failed` on the same step | error (never runs) |
| `if_prev_failed` on step 0 | warning (always skips) |

| Required args per action |
|---|
| `research` → `topic` |
| `alert` → `message` |
| `announce` → `text` |
| `scenario` → `name` |
| `takeover` → at least one of `type_text` / `keys` / `press_key` |
| `briefing` → none (defaults to `channels=["telegram"]`) |
| `look` → none |

What Phase 12 deliberately does **not** validate:

- `{{prev.<key>}}` placeholders against the prior step's result schema.
  Each action's result dict varies and some (scenario, briefing) are
  dynamic; better to leave a placeholder un-interpolated at runtime
  (current behavior) than to false-positive at validation time.
- Plan-level invariants like `rationale` length or `pre_checks` shape.
- Runtime conditions like network availability or whether `mobile_bridge`
  has a configured token — those belong with `integration_health`.

## Consistency check

Every output of `plan_builder.build_from_utterance()` is checked against
`plan_validator.validate()` in the commit message — all seven canonical
utterance shapes validate clean. Phase 10 and Phase 12 are consistent.

## Modules

| File | Tests | Purpose |
|---|---:|---|
| `plan_validator.py` | 16 | `validate(plan) → List[ValidationIssue]`; pure logic, never raises |

**16 new tests**, zero regression on the 1109-test Phase 11 baseline.

## How to enable

No flag — it's a library. Call from anywhere that builds a plan:

```python
issues = plan_validator.validate(plan)
errors = [i for i in issues if i.severity == plan_validator.SEVERITY_ERROR]
if errors:
    # log, abort, or fall back to a different plan
```

Or wire it into a future strict mode of `chain_executor.execute_chain`:

```python
def execute_chain(plan, strict=False):
    if strict:
        if any(i.severity == "error" for i in plan_validator.validate(plan)):
            return [{"ok": False, "skipped": True, "reason": "validation_failed"}]
    ...
```

## How to test

```bash
.venv/bin/python -m pytest tests/test_plan_validator.py -v
```

## What's next

- A `strict_validation: True` arg on `chain_executor.execute_chain` so
  validation can be opt-in at execution boundaries (e.g., the voice
  hook can validate before running).
- Placeholder schema check — track which result keys each action emits
  and warn when `{{prev.<key>}}` references a key that prior action
  doesn't produce. Requires a per-action result schema; defer until the
  schema is more stable.
- A small CLI: `python -m plan_validator <plan.json>` for ad-hoc plan files.
