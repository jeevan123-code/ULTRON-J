"""Tests for topic_detector — LLM filter on utterances."""
from unittest.mock import patch
import json
import pytest

from tests.fixtures.llm_mocks import fake_ask, register_response, clear_extra_responses


@pytest.fixture(autouse=True)
def _reset_mocks():
    yield
    clear_extra_responses()


def test_detect_topics_picks_research_worthy_proper_noun():
    import topic_detector as td
    register_response(
        "TOPIC_DETECTOR: I'm meeting Elon Musk tomorrow",
        json.dumps({"topics": [{"name": "Elon Musk", "priority": 3, "reason": "person reference"}]}),
    )
    with patch.object(td, "_llm_ask", side_effect=fake_ask):
        topics = td.detect_topics([{"text": "I'm meeting Elon Musk tomorrow", "ts": 0}])
    assert len(topics) == 1
    assert topics[0]["name"] == "Elon Musk"
    assert topics[0]["priority"] == 3


def test_detect_topics_skips_casual_chat():
    import topic_detector as td
    register_response(
        "TOPIC_DETECTOR: how are you today",
        json.dumps({"topics": []}),
    )
    with patch.object(td, "_llm_ask", side_effect=fake_ask):
        topics = td.detect_topics([{"text": "how are you today", "ts": 0}])
    assert topics == []


def test_detect_topics_returns_empty_on_llm_error():
    import topic_detector as td
    with patch.object(td, "_llm_ask", side_effect=RuntimeError("down")):
        topics = td.detect_topics([{"text": "anything", "ts": 0}])
    assert topics == []


def test_detect_topics_empty_input_returns_empty():
    import topic_detector as td
    assert td.detect_topics([]) == []


def test_detect_topics_caps_priority_to_range():
    """Priority values are clamped 1..5."""
    import topic_detector as td
    register_response(
        "TOPIC_DETECTOR: research wheat rust",
        json.dumps({"topics": [{"name": "wheat rust", "priority": 99}]}),
    )
    with patch.object(td, "_llm_ask", side_effect=fake_ask):
        topics = td.detect_topics([{"text": "research wheat rust", "ts": 0}])
    assert topics[0]["priority"] == 5
