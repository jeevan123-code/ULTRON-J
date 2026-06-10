# Phase 3c — Improvement Suggester + Hands-On Takeover

Status: SHIPPED on branch `phase3c-improvement`.

## What Phase 3c Builds

Two complementary upgrades that finish the Phase 3b consent loop.

### 1. Improvement suggester

Observes user actions, detects repetitive workflows (e.g., five file
renames in a row), and emits a `Suggestion` describing an automation
opportunity. *"Sir, may I write a batch-rename script for this?"*

### 2. Hands-on takeover

When the user replies HANDS_ON to a Phase 3c suggestion, the parked
`ExecutionPlan` (with `action="takeover"`) is dispatched through
`takeover_executor` into `computer_control` — typing text, hotkeys, or
single key presses. Flag-gated by `ULTRON_PHASE3C_ENABLED`; OFF by
default, so nothing reaches the user's machine unless explicitly enabled.

## End-to-end flow

```
[upstream observer]
    |
    v
action_log.record(ActionEvent)
    |
    v
improvement_suggester.analyze(events)  --> [Suggestion, Suggestion, ...]
    |
    v
proactive_offer.offer_takeover_suggestion(suggestion, ExecutionPlan)
    |
    v
[user speaks]  --> consent_manager.parse_consent -> ConsentMode.HANDS_ON
    |
    v
proactive_offer.confirm_offer(HANDS_ON)
    |
    +-- ULTRON_PHASE3C_ENABLED=1 -> takeover_executor.execute(plan)
    |                                  |
    |                                  +--> computer_control.type_text / hotkey / press_key
    |
    +-- flag OFF                 -> drop pending silently, return phase3c_disabled
```

## Modules

| File | Purpose |
|---|---|
| `action_types.py` | `ActionEvent` dataclass + `ActionKind` enum (FILE_RENAME, APP_LAUNCH, CLICK, TYPE, SHORTCUT_FIRE, OTHER). 6 tests. |
| `action_log.py` | Thread-safe rolling buffer of `ActionEvent`s, JSON-persistent at `action_log.json`. `record / recent / recent_count / _reset_for_test / _snapshot_for_test`. 9 tests. |
| `improvement_types.py` | `Suggestion` dataclass (kind / summary / template / supporting_events / confidence). 3 tests. |
| `improvement_suggester.py` | Pure pattern detection: `batch_rename` (5+ renames) + `morning_routine` (3+ identical launches in 30s). 8 tests. |
| `takeover_executor.py` | Wraps `computer_control.type_text / hotkey / press_key` behind an `ExecutionPlan` whose first step is `action="takeover"`. 6 tests. |
| `proactive_offer.py` | EXTENDED — `offer_takeover_suggestion` + flag-gated HANDS_ON branch routes through `takeover_executor`. 6 new tests; Phase 3b's 12 tests unaffected. |

## Reuses (untouched)

- Phase 1: `intent_types.ExecutionPlan`
- Phase 3b: `consent_types.ConsentMode`, `proactive_offer` pending-state machinery
- `computer_control.type_text / hotkey / press_key` (real-world UI side effects)

## How to enable

```bash
export ULTRON_PHASE3C_ENABLED=1
```

With the flag OFF, suggestions are still computed and offers can still be
parked — but `confirm_offer(HANDS_ON)` returns `{"reason": "phase3c_disabled"}`
without touching `computer_control`. This is the safe production default.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_action_types.py \
    tests/test_action_log.py \
    tests/test_improvement_types.py \
    tests/test_improvement_suggester.py \
    tests/test_takeover_executor.py \
    tests/test_phase3c_takeover_hook.py \
    tests/test_phase3c_integration.py -v
```

Phase 3c ships with **40 new tests**. Zero regression on Phase 3b's 12
`proactive_offer.py` tests or the 481-test capability baseline.

## What's next

- Phase 4: Multi-Device Coordination (House Party Protocol)
- Phase 6+: Wire upstream observers (filesystem watch / window focus
  events) to call `action_log.record` so the suggester runs over real data.
