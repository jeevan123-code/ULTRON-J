"""Tests for conversation_intelligence."""
from unittest.mock import patch
import pytest

from intent_types import IntentKind
from tests.fixtures.llm_mocks import fake_ask, register_response, clear_extra_responses
import json


@pytest.fixture(autouse=True)
def _reset_mocks():
    yield
    clear_extra_responses()


def test_detect_tone_casual_via_llm():
    import conversation_intelligence as ci
    register_response("TONE_OF_UTTERANCE: hey what's up", json.dumps({"tone": "casual"}))
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        tone = ci.detect_tone("hey what's up")
    assert tone == "casual"


def test_detect_tone_frustrated():
    import conversation_intelligence as ci
    register_response("TONE_OF_UTTERANCE: ugh this is broken again", json.dumps({"tone": "frustrated"}))
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        tone = ci.detect_tone("ugh this is broken again")
    assert tone == "frustrated"


def test_detect_tone_falls_back_on_llm_error():
    import conversation_intelligence as ci
    with patch.object(ci, "_llm_ask", side_effect=RuntimeError("network down")):
        tone = ci.detect_tone("anything")
    assert tone == "neutral"


def test_classify_intent_research():
    import conversation_intelligence as ci
    register_response(
        "CLASSIFY_INTENT: research wheat leaf rust",
        json.dumps({"kind": "research", "topic": "wheat leaf rust"}),
    )
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        intent = ci.classify_intent("research wheat leaf rust")
    assert intent.kind == IntentKind.RESEARCH
    assert intent.payload.get("topic") == "wheat leaf rust"


def test_classify_intent_command():
    import conversation_intelligence as ci
    register_response(
        "CLASSIFY_INTENT: open chrome",
        json.dumps({"kind": "command", "verb": "open", "target": "chrome"}),
    )
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        intent = ci.classify_intent("open chrome")
    assert intent.kind == IntentKind.COMMAND


def test_classify_intent_chat():
    import conversation_intelligence as ci
    register_response(
        "CLASSIFY_INTENT: how are you",
        json.dumps({"kind": "chat"}),
    )
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        intent = ci.classify_intent("how are you")
    assert intent.kind == IntentKind.CHAT


def test_classify_intent_falls_back_on_llm_error():
    import conversation_intelligence as ci
    with patch.object(ci, "_llm_ask", side_effect=RuntimeError("down")):
        intent = ci.classify_intent("anything goes here")
    assert intent.kind == IntentKind.CHAT
    assert intent.confidence < 0.5
