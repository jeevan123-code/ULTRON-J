"""Conversation Intelligence — natural language understanding layer.

Sits BEFORE every action. Takes a raw utterance + parsed primary intent + modifiers
(from compound_intent_parser) and enriches it with:
  - Tone detection (casual / urgent / frustrated / tired / neutral)
  - Reference resolution ("that thing" -> concrete item from memory)
  - Intent classification for free-form utterances (research / command / chat / clarify)

LLM-backed (uses llm_engine.ask), with deterministic fallbacks when LLM fails.
"""
import json
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
