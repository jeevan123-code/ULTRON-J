# Phase 5b — Stranger Detection + Privacy Circle

Status: SHIPPED on branch `phase5b-stranger-privacy`.

## What Phase 5b Builds

Closes the multi-person voice intelligence loop:

```
audio clip arrives
       |
       v
voice_id_pipeline.process_audio_clip(audio_path)
   |
   +-- voice_identity.get_embedding(audio_path)
   +-- speaker_diarizer.identify_speaker(embedding)
   |
   +-- if matched:
   |     room_awareness.record_voice(name)
   |     -> return {action: "recorded", name}
   |
   +-- if unmatched:
         room_awareness.record_voice("_stranger")
         stranger_offer.handle_stranger(StrangerEvent)
            |
            +-- rate-limit check (1 / 10 min)
            +-- voice_engine.tts("Sir, I hear a different voice. Should I remember them?")
            +-- store pending {embedding, audio_path, detected_at}
            |
            v
         [user speaks a reply: "That's Ravi, my brother" OR "skip it"]
            |
            v
         stranger_offer.confirm_stranger(reply)
            |
            +-- name_relation_parser.parse_name_relation(reply)
            +-- if resolved -> person_registry.register(Person(...))
            +-- if skip -> clear pending
            +-- if ambiguous -> keep pending
```

`privacy_circle.current_mode()` reports who's in the room as a single mode label.

## Modules

| File | Purpose |
|---|---|
| `voice_id_types.py` | `StrangerEvent`, `ParsedNameRelation` |
| `name_relation_parser.py` | `parse_name_relation(text) -> ParsedNameRelation` — deterministic kin/role keywords |
| `stranger_offer.py` | Pending state + rate-limited polite prompt + enrollment dispatch |
| `voice_id_pipeline.py` | Public `process_audio_clip(audio_path) -> Dict` orchestrator |
| `privacy_circle.py` | `current_mode(within_seconds=300) -> str` — mode label |

## Privacy modes

| Mode | When | Suggested downstream behavior |
|---|---|---|
| `stranger_present` | unknown voice OR unregistered name heard | suppress secrets, formal tone, no API keys spoken |
| `professional` | boss/colleague/client present | formal tone, no personal data |
| `friends` | friend present (no pro, no stranger) | casual but no work secrets |
| `family` | family present (no friends/pro/stranger) | casual; no API keys |
| `private` | only SELF or empty room | full assistant mode |

## Reuses (untouched)

- Phase 5a: `person_types`, `person_registry`, `speaker_diarizer`, `room_awareness`
- `voice_identity.get_embedding`
- `voice_engine.tts` (called inside `stranger_offer._speak` — a patchable seam)

## Integration

Phase 5b leaves `voice_engine.py` and `voice_routes.py` untouched. To wire it
into the live STT path, add a hook (typically in `voice_routes.py` after the
transcription succeeds):

```python
import os
if os.environ.get("ULTRON_PHASE5B_ENABLED", "0") == "1":
    try:
        from voice_id_pipeline import process_audio_clip
        process_audio_clip(audio_path)
    except Exception:
        pass
```

And inside `voice_engine.parse_voice_command`, after the Phase 3b consent
block, add:

```python
if os.environ.get("ULTRON_PHASE5B_ENABLED", "0") == "1":
    try:
        import stranger_offer as _so
        if _so.peek_pending() is not None:
            r = _so.confirm_stranger(text)
            if r.get("enrolled") or r.get("reason") == "skipped":
                return None
    except Exception:
        pass
```

These wirings are intentionally NOT in Phase 5b's commit set so that the
new code is fully testable in isolation.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_voice_id_types.py \
    tests/test_name_relation_parser.py \
    tests/test_stranger_offer.py \
    tests/test_voice_id_pipeline.py \
    tests/test_privacy_circle.py \
    tests/test_phase5b_integration.py -v
```

Phase 5b ships with 60 tests. Full ULTRON suite (baseline + Phase 1 + 2a
+ 2b + 3a + 3b + 5a + 5b) = **773 tests passing**, zero regression on
the original 481.

## What's next — Phase 5c

- Mood tracker + tone modulator (adjust voice mood by detected stress/calm)
- `pattern_learner.py` + `shortcut_inferrer.py` — learn workflows and slang
- Hook privacy_circle.current_mode into voice_engine to suppress secrets when stranger_present
