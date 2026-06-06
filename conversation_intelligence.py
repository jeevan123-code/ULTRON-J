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
