# Phase 4 — Multi-Device Coordination (House Party Protocol)

Status: SHIPPED on branch `phase4-house-party`.

## What Phase 4 Builds

A single voice trigger fans out to coordinated actions across every
device ULTRON can already control:

```
"Jarvis, house party protocol"
        |
        v
voice_engine.parse_voice_command (flag-gated)
        |
        v
multi_device_coordinator.match_trigger -> Scenario
        |
        v
multi_device_coordinator.run(scenario)
        |
        +--> _laptop_action  -> computer_control (hotkey lock / open_app / type_text)
        +--> _phone_action   -> mobile_bridge (do-not-disturb / message)
        +--> _smart_home_action -> smart_home (lights / lock_doors / lights_off)
        +--> _tv_action      -> stubbed (no TV module wired yet)
```

Each step is independent: one device dispatch raising an exception does
not abort the others. Step results are returned indexed by step number.

## Built-in scenarios

| Name | Trigger phrases | Steps |
|---|---|---|
| `house_party` | "house party", "house party protocol", "lockdown mode" | laptop lock, phone do-not-disturb, lights red, doors locked, TV to security view |
| `get_ready_for_call` | "get me ready for the call", "prep for the call", … | open Zoom on laptop, phone DND, lights warm-white |
| `bedtime` | "bedtime", "good night jarvis", "going to sleep" | lights off, phone DND, laptop lock |

Add custom scenarios at runtime via `multi_device_coordinator.register(Scenario(...))`.

## Modules

| File | Purpose |
|---|---|
| `scenario_types.py` | `Scenario` + `ScenarioStep` dataclasses with `matches_trigger`. 6 tests. |
| `multi_device_coordinator.py` | Thread-safe registry, `match_trigger`, `run`, per-target dispatcher functions. 8 tests. |
| `scenarios_builtin.py` | `register_builtins()` — canonical House Party / Get Ready / Bedtime. 5 tests. |
| `voice_engine.py` | MODIFIED — flag-gated hook at the top of `parse_voice_command` short-circuits on a scenario match. 4 new tests; Phase 3b/5d/5f integrations preserved. |

## How to enable

```bash
export ULTRON_PHASE4_ENABLED=1
```

Then once at startup:

```python
import scenarios_builtin
scenarios_builtin.register_builtins()
```

(Or register custom scenarios.)

## Defensive design

- Every per-target dispatcher wraps its module import in try/except, so
  a missing telegram token, missing Home Assistant config, or unavailable
  `computer_control` returns `{skipped: True, reason: ...}` and the rest
  of the scenario proceeds.
- The voice-engine hook is the only invasive change. Phase 1 / 2a / 2b /
  3b / 5d / 5f behaviour is preserved when ULTRON_PHASE4_ENABLED is OFF;
  when ON, a non-matching transcript falls through to the original flow.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_scenario_types.py \
    tests/test_multi_device_coordinator.py \
    tests/test_scenarios_builtin.py \
    tests/test_phase4_voice_hook.py \
    tests/test_phase4_integration.py -v
```

Phase 4 ships with **26 new tests**. Combined Phase 3c + Phase 4 add 66
tests on top of the 898-test Phase 5g baseline — zero regression on the
original 481 capability tests.

## What's next

- Live wiring of `action_log.record` to filesystem watchers and window
  focus events so Phase 3c's suggester sees real activity.
- A scenario-editor UI surface so the user can author scenarios without
  editing Python.
