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
