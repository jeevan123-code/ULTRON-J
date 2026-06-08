# Phase 5c — Mood Tracker + Tone Modulator

Status: SHIPPED on branch `phase5c-mood-tone`.

## What Phase 5c Builds

ULTRON adapts everything it says based on two signals:

```
                            mood_tracker.current_mood()
                                       |
   time of day  (hour buckets)         |
   + recent struggle count    --->  MoodState
                                       |
                                       v
                            tone_modulator.modulate(text, mood, privacy_mode)
                                       ^
                                       |
                privacy_circle.current_mode()
                            |
   room_awareness +         |
   person_registry  --->    privacy_mode
                            ("stranger_present" | "professional" | "friends" | "family" | "private")
```

`modulate()` does two things in order:
1. **Privacy redaction** — when `privacy_mode` is `stranger_present` or `professional`, replace API keys, bearer tokens, password assignments, env-style KEY/TOKEN/SECRET assignments, and `/home/jeevan/...` paths with `[redacted]`.
2. **Mood rewrite** — when mood is `TIRED`, prepend `"Take your time, sir. "`. When `FRUSTRATED`, drop filler prefixes like `Sir,` / `Here's what I found:` / `Let me see,`. `FOCUSED` / `NEUTRAL` / `RELAXED` leave text unchanged.

## Modules

| File | Purpose |
|---|---|
| `mood_types.py` | `MoodState` enum + `MoodReading` dataclass |
| `mood_tracker.py` | `current_mood(now, recent_struggles)` + `current_mood_reading(...)` — pure functions |
| `tone_modulator.py` | `modulate(text, mood, privacy_mode) -> str` |

## Reuses (untouched)

- Phase 5b: `privacy_circle.current_mode()` (consumed in integration test)
- No other prior-phase code touched

## How mood is inferred

| Hour | Mood | Reason label |
|---|---|---|
| 22..23, 0..5 | TIRED | `late_hour` |
| 6..11 | FOCUSED | `morning` |
| 12..16 | NEUTRAL | `afternoon` |
| 17..21 | RELAXED | `evening` |

If `recent_struggles >= 2` the time signal is overridden:
- mood becomes `FRUSTRATED`, reason `struggle_override`

## How privacy redaction works

Active modes (`stranger_present`, `professional`) trigger redaction. Each
match is replaced with `[redacted]`:

| Pattern | Example match |
|---|---|
| OpenAI-style API keys | `sk-XXXXXXXXXXXXXXXXXXXXXXXX` |
| Bearer tokens | `Bearer eyJhbGciOiJIUzI1NiIsInR5cCI` |
| Password / secret assignments | `password=hunter2`, `secret: abc` |
| Env-style KEY/TOKEN/SECRET (case-insensitive) | `api_KEY=...`, `OPENAI_API_KEY=...`, `MY_TOKEN=...` |
| Local home paths | `/home/jeevan/anything/here` |

`private`, `family`, `friends` leave secrets visible — those audiences are trusted.

## Public API

```python
from mood_tracker import current_mood
from tone_modulator import modulate
from privacy_circle import current_mode

mood = current_mood()                            # auto: time-of-day, no struggles
privacy = current_mode()                          # who's in the room right now
safe_text = modulate(raw, mood=mood, privacy_mode=privacy)
```

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_mood_types.py \
    tests/test_mood_tracker.py \
    tests/test_tone_modulator.py \
    tests/test_phase5c_integration.py -v
```

Phase 5c ships with 46 tests. Full ULTRON suite (baseline + Phase 1 + 2a
+ 2b + 3a + 3b + 5a + 5b + 5c) = **819 tests passing**, zero regression
on the original 481.

## Integration (deferred to Phase 5d)

Phase 5c keeps `voice_engine.py` untouched. To wire mood/privacy modulation
into every spoken response, a future hook in `voice_engine.tts` would call:

```python
from mood_tracker import current_mood
from privacy_circle import current_mode
from tone_modulator import modulate

text = modulate(text, mood=current_mood(), privacy_mode=current_mode())
```

before passing `text` to the TTS provider. Out-of-scope here so `modulate()`
stays a pure, easy-to-test function.

## What's next

- **Phase 5d** — wire mood/privacy into voice_engine.tts; track real struggle count from `[phase3a][stuck]` log; add `pattern_learner.py` for daily workflow detection.
- **Phase 3c** — improvement_suggester + true keyboard/mouse takeover.
- **Phase 4** — Multi-Device Coordination (House Party Protocol).
