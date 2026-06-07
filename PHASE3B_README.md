# Phase 3b — Interactive Co-Pilot

Status: SHIPPED on branch `phase3b-interactive-copilot`.

## What Phase 3b Builds

Closes the JARVIS co-pilot loop:

```
Phase 3a: StuckEvent emitted (error on screen for ≥30s)
                |
                v
screen_watcher._tick() (flag-gated) calls:
                |
                v
proactive_offer.handle_stuck_event(event)
   |
   +-- rate-limit check (1 offer / 5 min)
   +-- voice_engine.tts("Sir, mind if I help?")
   +-- store pending offer { error_text, active_window, offered_at }
                |
                v
        [user speaks a reply]
                |
                v
voice_engine.parse_voice_command(text) (flag-gated) calls:
   consent_manager.parse_consent(text) -> ConsentMode
   proactive_offer.confirm_offer(mode)
                |
                v
   HANDS_ON | VOICE_ONLY  -> phase2_executor.execute(ExecutionPlan{research, error_text})
   DECLINE                -> clear pending
   NONE                   -> keep pending (user hasn't decided yet)
```

## Modules

| File | Purpose |
|---|---|
| `consent_types.py` | `ConsentMode` enum: HANDS_ON / VOICE_ONLY / DECLINE / NONE |
| `consent_manager.py` | `parse_consent(text) -> ConsentMode` (deterministic, no LLM) |
| `proactive_offer.py` | Pending-offer state, rate-limited polite voice prompt, consent dispatch into Phase 2a research |

## Reuses (untouched)

- Phase 1: `intent_types.ExecutionPlan`
- Phase 2a: `phase2_executor.execute(plan)`, `research_engine.research()`, `delivery_manager`
- Phase 3a: `struggle_types.StuckEvent` (consumed); `screen_watcher._tick` extended with ONE flag-gated call
- `voice_engine.tts` for the polite prompt; one extra hook block in `parse_voice_command`

## How to enable

```bash
export ULTRON_PHASE3B_ENABLED=1
```

Then call `screen_watcher.start(poll_seconds=10)` at process startup. When a
persistent error is detected, ULTRON speaks "Sir, mind if I help?" — your
spoken reply is parsed, and on consent the error is researched via Phase 2a.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_consent_types.py \
    tests/test_consent_manager.py \
    tests/test_proactive_offer.py \
    tests/test_phase3b_integration.py -v
```

Phase 3b ships with 37 tests. Full ULTRON suite (baseline + Phase 1 +
2a + 2b + 3a + 3b) = **679 tests passing**, zero regression on the
original 481.

## What's next — Phase 3c and beyond

- `improvement_suggester.py` — workflow-pattern detection (needs an action log we don't yet have)
- True hands-on takeover via `computer_control` (Phase 3c)
- Phase 4: Multi-Device Coordination (House Party Protocol)
- Phase 5: Voice ID + Room Awareness + Mood / Privacy / Learning
