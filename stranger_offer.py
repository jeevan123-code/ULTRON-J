"""Stranger Offer — polite voice prompt + enrollment dispatch.

Lifecycle:
  1. voice_id_pipeline detects an unrecognised voice.
  2. handle_stranger(event):
       - rate-limit check (1 stranger offer per _RATE_LIMIT_SECONDS)
       - speak "Sir, I hear a different voice — should I remember them?"
       - store pending with embedding + audio_path
  3. voice_engine/voice_routes pipes the user's reply into confirm_stranger.
  4. confirm_stranger(reply):
       - name_relation_parser.parse_name_relation -> ParsedNameRelation
       - if resolved -> person_registry.register(Person(...))
       - if skip phrase -> clear pending
       - if ambiguous -> keep pending
"""
import threading
import time
from typing import Any, Dict, Optional

from name_relation_parser import parse_name_relation
from person_registry import register
from person_types import Person, Relation
from voice_id_types import StrangerEvent


_RATE_LIMIT_SECONDS = 600

_lock = threading.RLock()
_pending: Optional[Dict[str, Any]] = None
_last_offer_at: float = 0.0


def _reset_for_test() -> None:
    global _pending, _last_offer_at
    with _lock:
        _pending = None
        _last_offer_at = 0.0


def _speak(text: str) -> None:
    from voice_engine import tts
    tts(text, mood="FOCUSED")


def _now() -> float:
    return time.time()


def handle_stranger(event: StrangerEvent) -> bool:
    """Polite voice offer. Returns True if spoken, False if rate-limited."""
    global _pending, _last_offer_at
    with _lock:
        if _now() - _last_offer_at < _RATE_LIMIT_SECONDS:
            return False
        _last_offer_at = _now()
        _pending = {
            "embedding": list(event.embedding),
            "audio_path": event.audio_path,
            "detected_at": event.detected_at,
            "offered_at": _last_offer_at,
        }
    try:
        _speak("Sir, I hear a different voice. Should I remember them?")
    except Exception:
        try:
            with open("ultron_log.txt", "a") as f:
                f.write("[phase5b][voice_error] stranger offer failed\n")
        except Exception:
            pass
    return True


def peek_pending() -> Optional[Dict[str, Any]]:
    with _lock:
        return dict(_pending) if _pending else None


def confirm_stranger(reply: str) -> Dict[str, Any]:
    """Apply user reply to the current pending stranger offer."""
    global _pending
    with _lock:
        pending = _pending

    if pending is None:
        return {"enrolled": False, "reason": "no_pending"}

    parsed = parse_name_relation(reply or "")

    from name_relation_parser import _SKIP_PHRASES
    lc = (reply or "").strip().lower()
    is_skip = any(s in lc for s in _SKIP_PHRASES)

    if parsed.is_resolved:
        person = Person(
            name=parsed.name,
            relation=parsed.relation if parsed.relation != Relation.STRANGER else Relation.STRANGER,
            voiceprint=list(pending["embedding"]),
            enrolled_at=_now(),
            notes="enrolled via stranger workflow",
        )
        try:
            register(person)
        except Exception as e:
            return {"enrolled": False, "reason": "register_error", "error": repr(e)}
        with _lock:
            _pending = None
        return {
            "enrolled": True,
            "name": parsed.name,
            "relation": parsed.relation.value,
        }

    if is_skip:
        with _lock:
            _pending = None
        return {"enrolled": False, "reason": "skipped"}

    return {"enrolled": False, "reason": "unresolved"}
