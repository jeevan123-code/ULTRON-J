"""Compound Intent Parser.

Splits a single human utterance into a primary intent + optional modifiers.
"""
import re
from typing import List, Optional

from intent_types import Intent, Modifier, ParsedUtterance, IntentKind, ModifierKind


_AFFIRM_PHRASES = [
    "go ahead", "yeah man", "yes please", "do it", "sure thing", "do everything",
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

_PRIORITY_TRIGGERS = {
    "faster": "speed", "quickly": "speed", "make it faster": "speed",
    "slower": "slow", "carefully": "care",
}


def _phrase_match(text: str, phrases: List[str]) -> bool:
    lc = text.lower().strip()
    for p in phrases:
        if lc == p:
            return True
        for suffix in (" ", ",", ".", "!", "?", ";", ":"):
            if lc.startswith(p + suffix):
                return True
    return False


def detect_primary(text: str) -> Optional[IntentKind]:
    if _phrase_match(text, _AFFIRM_PHRASES):
        return IntentKind.AFFIRM
    if _phrase_match(text, _DENY_PHRASES):
        return IntentKind.DENY
    if _phrase_match(text, _DEFER_PHRASES):
        return IntentKind.DEFER
    return None


def _extract_modifiers(text: str) -> List[Modifier]:
    mods: List[Modifier] = []
    lc = text.lower()

    # PRIORITY (fastest / faster etc.)
    for trigger, val in _PRIORITY_TRIGGERS.items():
        if trigger in lc:
            mods.append(Modifier(kind=ModifierKind.PRIORITY, value=val))
            break  # only one priority per utterance

    # ADD: "and also add X", "also add X", "and add X", "and also X"
    for trig in ["and also add", "and add", "also add", "and also"]:
        m = re.search(rf"\b{re.escape(trig)}\b\s+(.+?)(?:\s+(?:and|but|except)\b|$)", lc)
        if m:
            value = m.group(1).strip().rstrip(".,!?")
            # Skip if the captured chunk is itself a known check/exclude phrase
            if not any(t in value for t in ["check if", "skip", "except"]):
                mods.append(Modifier(kind=ModifierKind.ADD, value=value))
                break

    # EXCLUDE: "except X", "but skip the X", "skip the X part", "without the X"
    for trig in ["except", "but skip the", "skip the", "without the"]:
        m = re.search(rf"\b{re.escape(trig)}\b\s+(.+?)(?:\s+(?:and|but)\b|$)", lc)
        if m:
            value = m.group(1).strip().rstrip(".,!?")
            # Strip trailing "part"
            value = re.sub(r"\s+part$", "", value)
            mods.append(Modifier(kind=ModifierKind.EXCLUDE, value=value))
            break

    # PRE_CHECK: "check if X", "check that X", "make sure X", "verify X"
    for trig in ["check if", "check that", "make sure", "verify"]:
        m = re.search(rf"\b{re.escape(trig)}\b\s+(.+?)(?:\s+first|\s+(?:and|but)\b|$)", lc)
        if m:
            value = m.group(1).strip().rstrip(".,!?")
            mods.append(Modifier(kind=ModifierKind.PRE_CHECK, value=value))
            break

    # SWITCH_TO
    for trig in ["do the other one instead", "the other one instead", "the previous one"]:
        if trig in lc:
            mods.append(Modifier(kind=ModifierKind.SWITCH_TO, value="previous_option"))
            break

    return mods


def parse(text: str) -> ParsedUtterance:
    """Parse a raw utterance into a ParsedUtterance with primary intent + modifiers."""
    primary_kind = detect_primary(text)
    if primary_kind is None:
        primary = Intent(kind=IntentKind.CHAT, payload={"raw": text}, confidence=0.3)
    else:
        primary = Intent(kind=primary_kind, payload={}, confidence=0.9)

    modifiers = _extract_modifiers(text)
    return ParsedUtterance(raw=text, primary=primary, modifiers=modifiers)
