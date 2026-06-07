# Phase 3a — Passive Screen Watching + Struggle Detection

Status: SHIPPED on branch `phase3a-screen-watcher`.

## What Phase 3a Builds

ULTRON now watches your screen at low frequency, recognises when the SAME
error has been visible for too long, and emits a structured `StuckEvent` —
the foundation Phase 3b will use to politely offer help.

```
screen_engine.detect_errors_on_screen()
            |
            v
screen_watcher.take_snapshot()
            |
            +-- classify_sensitivity()        <-- pause on banking/passwords/secrets
            +-- normalize_error_signature()
            |
            v
struggle_detector.ingest(snapshot)
            |
            v
StuckEvent (kind=error_persistent, duration_seconds, snapshot)
            |
            v
ultron_log.txt   [phase3a][stuck] {...}
```

## Modules

| File | Purpose |
|---|---|
| `struggle_types.py` | `ScreenSnapshot`, `StuckEvent`, `StuckKind`, `SensitivityKind` |
| `struggle_detector.py` | Pure state machine: persistence threshold, single-emit-per-signature |
| `screen_watcher.py` | Background loop polling screen_engine every 10s; sensitivity classification; `ULTRON_EYES_CLOSED` off-switch |

## Reuses (untouched)

- `screen_engine.py` — `detect_errors_on_screen()`
- `perception.py`, `screen_parser.py`, `visual_verify.py`

## How to enable

Call `screen_watcher.start(poll_seconds=10)` once at process startup
(e.g., in `app.py`'s init block).

To pause passively at any moment:

```bash
export ULTRON_EYES_CLOSED=1
```

The watcher continues to spin but every `_tick()` is a no-op until the
environment variable is cleared.

## Sensitive screens auto-pause

The watcher classifies each snapshot as one of `none`, `banking`,
`password_field`, or `secret_file`. Anything other than `none` skips
the detector entirely — ULTRON never reasons about banking pages or
password fields.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_struggle_types.py \
    tests/test_struggle_detector.py \
    tests/test_screen_watcher.py \
    tests/test_phase3a_integration.py -v
```

Phase 3a ships with 22 tests. Full ULTRON suite (baseline + Phase 1 +
2a + 2b + 3a) = **642 tests passing** with zero regression on the
original 481.

## What's next — Phase 3b

The interactive layer: `proactive_offer.py` (decide WHEN to interrupt),
`consent_manager.py` (parse hands-on vs voice-only response),
`improvement_suggester.py` (suggest better approaches when ULTRON sees
a suboptimal workflow). Phase 3b subscribes to the `[phase3a][stuck]`
events Phase 3a is now emitting.
