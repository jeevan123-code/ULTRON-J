# Phase 5d — Live Voice Integration

Status: SHIPPED on branch `phase5d-voice-integration`.

## What Phase 5d Builds

Phases 5a/5b/5c were libraries. Phase 5d wires them into the live voice path.

```
screen_watcher._tick()  (every 10s)
        |
        v
  struggle_detector.ingest(snap) emits StuckEvent
        |
        v
  struggle_counter.record_struggle(ts)   <-- Phase 5d (flag-gated)
        |
        v
  ... time passes, ULTRON wants to speak ...
        |
        v
voice_engine.tts(text, ...)
        |
        +-- Phase 5d hook (flag-gated):
        |      recent_struggles = struggle_counter.recent_count(within_seconds=3600)
        |      mood = mood_tracker.current_mood(recent_struggles=recent_struggles)
        |      privacy = privacy_circle.current_mode()
        |      text = tone_modulator.modulate(text, mood=mood, privacy_mode=privacy)
        |
        v
prepare_for_tts(text) -> TTS provider chain (existing)
```

Result: EVERY spoken response is automatically redacted when strangers/pros
are present and tone-shifted based on time of day + recent struggles.

## Modules

| File | Purpose |
|---|---|
| `struggle_counter.py` | NEW — thread-safe rolling log of struggle timestamps. `record_struggle`, `recent_count(within_seconds=3600, now)` |
| `screen_watcher.py` | MODIFIED — `_tick` now calls `struggle_counter.record_struggle(event.last_seen_ts)` when ULTRON_PHASE5D_ENABLED=1 |
| `voice_engine.py` | MODIFIED — top of `tts()` modulates text via mood + privacy when ULTRON_PHASE5D_ENABLED=1 |

## How to enable

```bash
export ULTRON_PHASE5D_ENABLED=1
# also requires Phase 3a watcher: screen_watcher.start(poll_seconds=10) at startup
```

The voice hook is robust: if any of the Phase 5 imports / lookups fail, it
silently falls back to raw text. No spoken responses can be blocked.

The screen-watcher hook is similarly safe: any counter failure is logged
to `ultron_log.txt` but doesn't break the watcher.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_struggle_counter.py \
    tests/test_phase5d_integration.py -v
```

Phase 5d ships with 14 tests. Full ULTRON suite (baseline + Phase 1 + 2a +
2b + 3a + 3b + 5a + 5b + 5c + 5d) = **833 tests passing**, zero regression
on the original 481.

## Verification one-liner (flag ON)

```bash
ULTRON_PHASE5D_ENABLED=1 .venv/bin/python -c "
from unittest.mock import patch
import voice_engine as ve, room_awareness as ra
ra._reset_for_test()
ra.record_voice('_stranger')
captured = {}
def cap(t):
    captured['text'] = t
    return 'OK'
with patch.object(ve, 'prepare_for_tts', cap), \
     patch.object(ve, '_tts_edge', lambda t,m: b''), \
     patch.object(ve, '_get_cached', lambda *a, **kw: None), \
     patch.object(ve, '_set_cached', lambda *a, **kw: None), \
     patch.object(ve, '_log_voice', lambda *a, **kw: None):
    ve.tts('My password=hunter2.', provider='edge')
print(captured['text'])
"
# Expected: 'My [redacted].'
```

## What's next

- **Phase 5e** — `pattern_learner.py` + `shortcut_inferrer.py` (workflow learning)
- **Phase 3c** — improvement_suggester + true keyboard/mouse takeover
- **Phase 4** — Multi-Device Coordination (House Party Protocol)
