"""Compound Intent Parser.

Splits a single human utterance into a primary intent + optional modifiers.

Examples:
    "yes" -> primary=AFFIRM
    "yes and also add voice activation" -> primary=AFFIRM, modifiers=[ADD voice activation]
    "nah, do the other one instead" -> primary=DENY, modifiers=[SWITCH_TO previous_option]
"""
import re
from typing import List, Optional

from intent_types import Intent, Modifier, ParsedUtterance, IntentKind, ModifierKind


# Phrase vocab — order matters (longest match first within each category).
_AFFIRM_PHRASES = [
    "go ahead", "yeah man", "yes please", "do it", "sure thing",
    "yes", "yep", "yeah", "sure", "ok", "okay", "bet", "yup", "aye",
    "alright", "fine", "cool",
]
_DENY_PHRASES = [
    "no thanks", "not now", "skip it", "forget it", "skip that",
    "no", "nah", "nope", "negative", "don't", "do not",
]
_DEFER_PHRASES = [
    "hmm let me think", "let me think", "hold on", "one moment",
    "wait", "pause", "hmm",
]


def _phrase_match(text: str, phrases: List[str]) -> bool:
    lc = text.lower().strip()
    # Match whole utterance OR utterance starting with phrase followed by space/punct
    for p in phrases:
        if lc == p:
            return True
        for suffix in (" ", ",", ".", "!", "?", ";", ":"):
            if lc.startswith(p + suffix):
                return True
    return False


def detect_primary(text: str) -> Optional[IntentKind]:
    """Return the primary IntentKind for known short utterances, or None."""
    if _phrase_match(text, _AFFIRM_PHRASES):
        return IntentKind.AFFIRM
    if _phrase_match(text, _DENY_PHRASES):
        return IntentKind.DENY
    if _phrase_match(text, _DEFER_PHRASES):
        return IntentKind.DEFER
    return None


def parse(text: str) -> ParsedUtterance:
    """Parse a raw utterance into a ParsedUtterance."""
    primary_kind = detect_primary(text)
    if primary_kind is None:
        # Will be enriched by conversation_intelligence.py later
        primary = Intent(kind=IntentKind.CHAT, payload={"raw": text}, confidence=0.3)
    else:
        primary = Intent(kind=primary_kind, payload={}, confidence=0.9)
    return ParsedUtterance(raw=text, primary=primary, modifiers=[])
