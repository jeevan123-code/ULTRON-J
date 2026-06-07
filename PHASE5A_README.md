# Phase 5a — Voice ID + Person Registry

Status: SHIPPED on branch `phase5a-voice-id`.

## What Phase 5a Builds

Multi-person voice recognition. ULTRON can:
- Register multiple known people (Jeevan, family, friends, professionals)
- Identify which registered person is currently speaking via cosine similarity
- Track which voices have been heard recently (who is in the room right now)

The foundation for Phase 5b's stranger-detection workflow ("Sir, I hear a
different voice — should I remember them?") and privacy-circle behavior shifts.

## Modules

| File | Purpose |
|---|---|
| `person_types.py` | `Person` dataclass + `Relation` enum + `RecognitionResult` |
| `person_registry.py` | JSON-backed CRUD at `voice_identity/persons/{slug}.json` — register, get, list_all, delete, iter_voiceprints |
| `speaker_diarizer.py` | `identify_speaker(embedding, threshold=0.75) -> RecognitionResult` — pure numpy, true cosine similarity |
| `room_awareness.py` | Thread-safe rolling log — `record_voice`, `last_seen`, `who_is_in_the_room(within_seconds=300)` |

## Reuses (untouched)

- `voice_identity.py` — caller produces embeddings via the existing `get_embedding(audio_path)` and feeds them to `speaker_diarizer.identify_speaker`.

## Public API

```python
from person_types import Person, Relation
import person_registry, speaker_diarizer, room_awareness
import voice_identity
import time

# Enroll a new person (requires an audio file already on disk).
embedding = voice_identity.get_embedding("/tmp/ravi-sample.wav")
person_registry.register(Person(
    name="Ravi", relation=Relation.FAMILY,
    voiceprint=list(embedding), enrolled_at=time.time(), notes="brother",
))

# At runtime, classify each incoming voice clip:
incoming = voice_identity.get_embedding("/tmp/incoming.wav")
result = speaker_diarizer.identify_speaker(incoming)
if result.matched:
    print(f"That's {result.name} ({result.similarity:.2f} confidence)")
    room_awareness.record_voice(result.name)
else:
    print("Unknown voice — Phase 5b will ask if I should remember them")

# Query who's currently around (last 5 minutes by default):
print("In the room:", room_awareness.who_is_in_the_room())
```

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_person_types.py \
    tests/test_person_registry.py \
    tests/test_speaker_diarizer.py \
    tests/test_room_awareness.py \
    tests/test_phase5a_integration.py -v
```

Phase 5a ships with 34 tests. Full ULTRON suite (baseline + Phase 1 + 2a +
2b + 3a + 3b + 5a) = **713 tests passing**, zero regression on the original
481.

## Storage layout

```
voice_identity/
├── voiceprint.json          # legacy single-Jeevan store from voice_identity.py (untouched)
└── persons/                 # NEW Phase 5a multi-person store
    ├── jeevan.json
    ├── ravi.json
    └── pepper.json
```

Each `persons/*.json` file:
```json
{
  "name": "Ravi",
  "relation": "family",
  "voiceprint": [0.012, -0.034, 0.087, ...],
  "enrolled_at": 1717800000.0,
  "notes": "brother"
}
```

## What's next — Phase 5b

Stranger-detection workflow: voice_engine hook that runs `identify_speaker`
on every transcribed clip, and when no one passes the threshold, ULTRON
politely says "Sir, I hear a different voice — should I remember them?"
Followed by `privacy_circle.py` — behavior shifts based on who is in the room.
