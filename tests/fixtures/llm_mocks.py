"""Deterministic LLM mocks for Phase 1 tests.

These replace calls to llm_engine.ask() so tests are fast and reproducible.
Each mock is keyed by the substring it expects to see in the prompt; the first
match wins. Add cases as new tests need them.
"""
import json
from typing import Callable, Dict


# Substring -> JSON-string response the LLM "would have returned"
_RESPONSES: Dict[str, str] = {
    # tone detection prompts
    "TONE_OF_UTTERANCE": json.dumps({"tone": "casual"}),

    # intent classification prompts
    "CLASSIFY_INTENT": json.dumps({"kind": "research", "topic": "wheat rust"}),

    # reference resolution
    "RESOLVE_REFERENCE: that thing": json.dumps({"resolved": "wheat-3d-explorer", "confidence": 0.85}),

    # reasoning / planning
    "PLAN_FROM_INTENT": json.dumps({
        "steps": [{"action": "research", "args": {"topic": "wheat rust"}}],
        "pre_checks": [],
        "rationale": "user asked to research wheat rust"
    }),
}


def fake_ask(prompt: str, **kwargs) -> str:
    """Drop-in replacement for llm_engine.ask().

    Returns the response for the LONGEST matching substring key, so registered
    specific keys override shorter defaults.
    Raises if no case matches — forces tests to be explicit.
    """
    matching = [k for k in _RESPONSES if k in prompt]
    if not matching:
        raise AssertionError(f"No mock response matches prompt: {prompt[:200]}")
    return _RESPONSES[max(matching, key=len)]


def register_response(key: str, response: str) -> None:
    """Allow tests to inject extra mock responses inline."""
    _RESPONSES[key] = response


def clear_extra_responses() -> None:
    """Reset to defaults (call in test teardown)."""
    keys_to_remove = [k for k in _RESPONSES if k not in _DEFAULT_KEYS]
    for k in keys_to_remove:
        del _RESPONSES[k]


_DEFAULT_KEYS = set(_RESPONSES.keys())
