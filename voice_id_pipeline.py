"""Voice ID Pipeline — public entry point.

Call `process_audio_clip(path)` whenever you have a transcribed audio clip
and want ULTRON to figure out who said it. The pipeline:

  1. Extract the embedding via voice_identity.get_embedding (mockable seam).
  2. Identify the speaker via speaker_diarizer.identify_speaker.
  3a. If matched -> room_awareness.record_voice(name); return {action: "recorded"}
  3b. If unmatched -> stranger_offer.handle_stranger(...) + record "_stranger";
                       return {action: "stranger_offer"}

Tests patch _get_embedding to skip real audio.
"""
import time
from typing import Any, Dict, Optional

import numpy as np

import room_awareness
import speaker_diarizer
import stranger_offer
from voice_id_types import StrangerEvent


_STRANGER_SENTINEL = "_stranger"


def _get_embedding(audio_path: str) -> Optional[np.ndarray]:
    """Indirection so tests can patch without calling the real ECAPA-TDNN."""
    try:
        from voice_identity import get_embedding
        return get_embedding(audio_path)
    except Exception:
        return None


def process_audio_clip(audio_path: str) -> Dict[str, Any]:
    """Take one audio clip path through the full Phase 5b voice-ID pipeline."""
    if not audio_path or not str(audio_path).strip():
        return {"action": "skipped", "reason": "no_audio_path"}

    embedding = _get_embedding(audio_path)
    if embedding is None:
        return {"action": "skipped", "reason": "no_embedding"}

    result = speaker_diarizer.identify_speaker(embedding)
    if result.matched:
        room_awareness.record_voice(result.name)
        return {
            "action": "recorded",
            "name": result.name,
            "similarity": result.similarity,
        }

    room_awareness.record_voice(_STRANGER_SENTINEL)
    event = StrangerEvent(
        embedding=list(np.asarray(embedding, dtype=float).tolist()),
        audio_path=audio_path,
        detected_at=time.time(),
    )
    spoken = stranger_offer.handle_stranger(event)
    return {
        "action": "stranger_offer",
        "spoken": spoken,
        "similarity": result.similarity,
    }
