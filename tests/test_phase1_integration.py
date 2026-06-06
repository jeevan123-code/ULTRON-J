"""End-to-end Phase 1: utterance -> parsed -> enriched -> planned.

Verifies the three new modules compose correctly through the public API.
"""
import json
from unittest.mock import patch
import pytest

from compound_intent_parser import parse
import conversation_intelligence as ci
import reasoning_layer as rl
from intent_types import IntentKind, ModifierKind
from tests.fixtures.llm_mocks import fake_ask, register_response, clear_extra_responses


@pytest.fixture(autouse=True)
def _reset():
    yield
    clear_extra_responses()


def test_compound_affirm_with_modifiers_produces_correct_plan():
    """The headline scenario: 'yes and also add voice activation and check wifi first'
    after a research action was proposed."""
    raw = "yes and also add voice activation and check if the wifi is on first"

    register_response(f"TONE_OF_UTTERANCE: {raw}", json.dumps({"tone": "casual"}))

    parsed = parse(raw)
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        enriched = ci.enrich(parsed, context={})

    assert enriched.primary.kind == IntentKind.AFFIRM
    kinds = {m.kind for m in enriched.modifiers}
    assert ModifierKind.ADD in kinds
    assert ModifierKind.PRE_CHECK in kinds

    last_action = {"action": "research", "args": {"topic": "wheat rust"}}
    plan = rl.plan(enriched, last_action=last_action)

    assert any(s["action"] == "research" for s in plan.steps)
    assert any(s["action"] == "add_feature" and "voice activation" in str(s["args"]).lower() for s in plan.steps)
    assert any("wifi" in pc.lower() for pc in plan.pre_checks)


def test_free_form_research_request_produces_research_plan():
    raw = "research wheat leaf rust deeply"
    register_response(f"TONE_OF_UTTERANCE: {raw}", json.dumps({"tone": "neutral"}))
    register_response(
        f"CLASSIFY_INTENT: {raw}",
        json.dumps({"kind": "research", "topic": "wheat leaf rust"}),
    )

    parsed = parse(raw)
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        enriched = ci.enrich(parsed, context={})
    plan = rl.plan(enriched, last_action=None)

    assert plan.steps[0]["action"] == "research"
    assert plan.steps[0]["args"]["topic"] == "wheat leaf rust"


def test_deny_cancels_pending_action():
    raw = "nah skip it"
    register_response(f"TONE_OF_UTTERANCE: {raw}", json.dumps({"tone": "casual"}))

    parsed = parse(raw)
    with patch.object(ci, "_llm_ask", side_effect=fake_ask):
        enriched = ci.enrich(parsed, context={})
    plan = rl.plan(enriched, last_action={"action": "research", "args": {}})

    assert plan.steps[0]["action"] == "cancel"
