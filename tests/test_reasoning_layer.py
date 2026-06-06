"""Tests for reasoning_layer."""
import json
from unittest.mock import patch
import pytest

from compound_intent_parser import parse
from intent_types import IntentKind, ModifierKind, Modifier, Intent, ParsedUtterance, ExecutionPlan
from tests.fixtures.llm_mocks import fake_ask, register_response, clear_extra_responses


@pytest.fixture(autouse=True)
def _reset_mocks():
    yield
    clear_extra_responses()


def test_plan_for_simple_research():
    import reasoning_layer as rl
    parsed = ParsedUtterance(
        raw="research wheat leaf rust",
        primary=Intent(kind=IntentKind.RESEARCH, payload={"topic": "wheat leaf rust"}, confidence=0.9),
    )
    plan = rl.plan(parsed, last_action=None)
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) == 1
    assert plan.steps[0]["action"] == "research"
    assert plan.steps[0]["args"]["topic"] == "wheat leaf rust"
    assert plan.pre_checks == []


def test_plan_for_affirm_carries_last_action():
    """AFFIRM means proceed with the last proposed action."""
    import reasoning_layer as rl
    parsed = ParsedUtterance(
        raw="yes go ahead",
        primary=Intent(kind=IntentKind.AFFIRM, payload={}, confidence=0.95),
    )
    last_action = {"action": "research", "args": {"topic": "X"}}
    plan = rl.plan(parsed, last_action=last_action)
    assert plan.steps[0] == last_action


def test_plan_for_affirm_no_last_action_returns_clarify():
    """AFFIRM with nothing to confirm -> ask for clarification."""
    import reasoning_layer as rl
    parsed = ParsedUtterance(
        raw="yes",
        primary=Intent(kind=IntentKind.AFFIRM, payload={}, confidence=0.95),
    )
    plan = rl.plan(parsed, last_action=None)
    assert plan.steps[0]["action"] == "clarify"


def test_plan_applies_pre_check_modifier():
    import reasoning_layer as rl
    parsed = ParsedUtterance(
        raw="yes and check wifi first",
        primary=Intent(kind=IntentKind.AFFIRM, payload={}, confidence=0.95),
        modifiers=[Modifier(kind=ModifierKind.PRE_CHECK, value="wifi on")],
    )
    last_action = {"action": "research", "args": {"topic": "X"}}
    plan = rl.plan(parsed, last_action=last_action)
    assert "wifi on" in plan.pre_checks


def test_plan_applies_exclude_modifier():
    import reasoning_layer as rl
    parsed = ParsedUtterance(
        raw="yes but skip the email part",
        primary=Intent(kind=IntentKind.AFFIRM, payload={}, confidence=0.95),
        modifiers=[Modifier(kind=ModifierKind.EXCLUDE, value="email")],
    )
    last_action = {"action": "daily_briefing", "args": {"include": ["email", "calendar", "news"]}}
    plan = rl.plan(parsed, last_action=last_action)
    included = plan.steps[0]["args"].get("include", [])
    assert "email" not in included
    assert "calendar" in included


def test_plan_for_deny_returns_cancel_step():
    import reasoning_layer as rl
    parsed = ParsedUtterance(
        raw="no",
        primary=Intent(kind=IntentKind.DENY, payload={}, confidence=0.95),
    )
    plan = rl.plan(parsed, last_action={"action": "research", "args": {}})
    assert plan.steps[0]["action"] == "cancel"


def test_plan_for_defer_returns_pause_step():
    import reasoning_layer as rl
    parsed = ParsedUtterance(
        raw="wait",
        primary=Intent(kind=IntentKind.DEFER, payload={}, confidence=0.95),
    )
    plan = rl.plan(parsed, last_action={"action": "x", "args": {}})
    assert plan.steps[0]["action"] == "pause"
