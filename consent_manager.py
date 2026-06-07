"""Consent manager — parse a transcript into a ConsentMode.

Deterministic keyword matching. No LLM call. Order matters:

  1. DECLINE phrases (most specific negatives)
  2. VOICE_ONLY phrases ("just tell me", "describe", "your thought")
  3. HANDS_ON phrases ("take over", "fix it", "do it", "help me")
  4. AFFIRM-only ("yes", "yeah", "sure") with no qualifier -> HANDS_ON default
  5. Fallback -> NONE
"""
from typing import List

from consent_types import ConsentMode


_DECLINE_PHRASES: List[str] = [
    "no thanks", "no thank you", "i got it", "i've got it", "ive got it",
    "not now", "skip it", "skip that", "forget it", "nope",
    "i don't need help", "i dont need help", "i don't need", "i dont need",
    "no",
]

_VOICE_ONLY_PHRASES: List[str] = [
    "just tell me", "tell me what", "tell me the", "tell me how",
    "say your thought", "say it", "voice only", "voice-only",
    "only describe", "describe it", "describe what",
    "only tell", "but tell",
]

_HANDS_ON_PHRASES: List[str] = [
    "take over", "go ahead and take",
    "fix it", "fix this", "do it for me", "do it", "fix it for me",
    "go ahead", "help me", "you can",
]

_AFFIRM_FALLBACK_PHRASES: List[str] = [
    "yes", "yeah", "yep", "sure", "ok", "okay", "bet", "alright", "cool",
]


def _contains_any(text_lc: str, phrases: List[str]) -> bool:
    return any(p in text_lc for p in phrases)


def parse_consent(text: str) -> ConsentMode:
    """Return the ConsentMode that best matches the utterance, or NONE."""
    if not text or not text.strip():
        return ConsentMode.NONE
    lc = text.strip().lower()

    if _contains_any(lc, _DECLINE_PHRASES):
        return ConsentMode.DECLINE
    if _contains_any(lc, _VOICE_ONLY_PHRASES):
        return ConsentMode.VOICE_ONLY
    if _contains_any(lc, _HANDS_ON_PHRASES):
        return ConsentMode.HANDS_ON
    if _contains_any(lc, _AFFIRM_FALLBACK_PHRASES):
        return ConsentMode.HANDS_ON
    return ConsentMode.NONE
