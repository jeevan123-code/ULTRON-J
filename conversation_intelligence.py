"""Conversation Intelligence — natural language understanding layer.

Sits BEFORE every action. Takes a raw utterance + parsed primary intent + modifiers
(from compound_intent_parser) and enriches it with:
  - Tone detection (casual / urgent / frustrated / tired / neutral)
  - Reference resolution ("that thing" -> concrete item from memory)
  - Intent classification for free-form utterances (research / command / chat / clarify)

LLM-backed (uses llm_engine.ask), with deterministic fallbacks when LLM fails.
"""
import json
import re
from typing import Any, Dict, Optional

from intent_types import Intent, IntentKind, ParsedUtterance


def _llm_ask(prompt: str, **kwargs) -> str:
    from llm_engine import ask
    return ask(prompt, **kwargs)


_TONE_PROMPT = """TONE_OF_UTTERANCE: {raw}

Classify the speaker's tone in one of: casual, urgent, frustrated, tired, neutral.
Respond ONLY with JSON: {{"tone": "<one_of_those>"}}.
"""


def detect_tone(raw: str) -> str:
    """Detect tone of an utterance. Returns 'neutral' on any error."""
    try:
        resp = _llm_ask(_TONE_PROMPT.format(raw=raw))
        data = json.loads(resp)
        tone = data.get("tone", "neutral")
        if tone in {"casual", "urgent", "frustrated", "tired", "neutral"}:
            return tone
        return "neutral"
    except Exception:
        return "neutral"


_CLASSIFY_PROMPT = """CLASSIFY_INTENT: {raw}

Classify the utterance into one of:
  - research  : user wants information on a topic
  - command   : user wants the system to do an action (open app, file op, etc.)
  - chat      : casual conversation, no actionable request
  - clarify   : the utterance is ambiguous and needs follow-up

Respond ONLY with JSON: {{"kind": "<one_of_those>", "topic": "<optional>", "verb": "<optional>", "target": "<optional>"}}
"""


_VALID_KINDS = {"research", "command", "chat", "clarify"}


def classify_intent(raw: str) -> Intent:
    """Classify a free-form utterance into an Intent.

    Returns Intent(kind=CHAT, confidence=0.3) on any error — caller decides how to handle.
    """
    try:
        resp = _llm_ask(_CLASSIFY_PROMPT.format(raw=raw))
        data = json.loads(resp)
        kind_str = data.get("kind", "chat")
        if kind_str not in _VALID_KINDS:
            kind_str = "chat"
        kind = IntentKind(kind_str)
        payload = {k: v for k, v in data.items() if k != "kind"}
        return Intent(kind=kind, payload=payload, confidence=0.85)
    except Exception:
        return Intent(kind=IntentKind.CHAT, payload={"raw": raw}, confidence=0.3)


_REFERENCE_PATTERNS = [
    r"that thing(?: we discussed)?",
    r"the (\w+) (?:thing|project|stuff)",
    r"that guy",
    r"that one",
    r"the other one",
    r"the previous one",
]


def _has_referent(text: str) -> Optional[str]:
    """Return the matched reference phrase if found, else None."""
    lc = text.lower()
    for pat in _REFERENCE_PATTERNS:
        m = re.search(pat, lc)
        if m:
            return m.group(0)
    return None


_RESOLVE_PROMPT = """RESOLVE_REFERENCE: {phrase}

Recent conversation context:
{context_json}

The user said something containing the reference "{phrase}". Based on the context,
what concrete item is being referred to? Respond ONLY with JSON:
{{"resolved": "<concrete item>", "confidence": <0.0..1.0>}}
"""


def resolve_references(raw: str, context: Dict[str, Any]) -> Dict[str, str]:
    """Resolve ambiguous references like 'that thing' against recent context.

    Returns {phrase: resolved_item} for each reference found, or {} if none.
    """
    phrase = _has_referent(raw)
    if not phrase:
        return {}
    try:
        resp = _llm_ask(_RESOLVE_PROMPT.format(phrase=phrase, context_json=json.dumps(context)))
        data = json.loads(resp)
        resolved = data.get("resolved")
        if resolved and data.get("confidence", 0) >= 0.5:
            return {phrase: resolved}
        return {}
    except Exception:
        return {}


def enrich(parsed: ParsedUtterance, context: Dict[str, Any]) -> ParsedUtterance:
    """Enrich a ParsedUtterance with tone, references, and (if chat/unknown) intent classification.

    Mutates and returns the same ParsedUtterance for convenience.
    """
    parsed.tone = detect_tone(parsed.raw)
    parsed.references = resolve_references(parsed.raw, context)

    if parsed.primary.kind == IntentKind.CHAT and parsed.primary.confidence < 0.5:
        parsed.primary = classify_intent(parsed.raw)

    return parsed
