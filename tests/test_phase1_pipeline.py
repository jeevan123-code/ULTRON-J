"""Tests for the Phase 1 wrapper pipeline."""
import json
from unittest.mock import patch
import pytest

from phase1_pipeline import process_user_utterance
import conversation_intelligence as ci
from intent_types import IntentKind
from tests.fixtures.llm_mocks import fake_ask, register_response, clear_extra_responses


@pytest.fixture(autouse=True)
def _reset():
    yield
    clear_extra_responses()


def test_process_user_utterance_returns_execution_plan_for_affirm():
    register_response("TONE_OF_UTTERANCE: yes go ahead", json.dumps({"tone": "casual"}))
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        plan = process_user_utterance(
            raw="yes go ahead",
            context={},
            last_action={"action": "research", "args": {"topic": "x"}},
        )
    assert plan.steps[0]["action"] == "research"


def test_process_user_utterance_resolves_reference_in_context():
    register_response("TONE_OF_UTTERANCE: research that thing",
                      json.dumps({"tone": "neutral"}))
    register_response("RESOLVE_REFERENCE: that thing",
                      json.dumps({"resolved": "wheat-3d-explorer", "confidence": 0.85}))
    register_response("CLASSIFY_INTENT: research that thing",
                      json.dumps({"kind": "research", "topic": "wheat-3d-explorer"}))

    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        plan = process_user_utterance(
            raw="research that thing",
            context={"recent_topics": ["wheat-3d-explorer"]},
            last_action=None,
        )
    assert plan.steps[0]["action"] == "research"
    assert "wheat-3d-explorer" in str(plan.steps[0]["args"]).lower()
