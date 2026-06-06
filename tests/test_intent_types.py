"""Tests for shared intent dataclasses."""
from intent_types import Intent, Modifier, ParsedUtterance, ExecutionPlan, IntentKind, ModifierKind


def test_intent_kind_values():
    assert IntentKind.AFFIRM.value == "affirm"
    assert IntentKind.DENY.value == "deny"
    assert IntentKind.DEFER.value == "defer"
    assert IntentKind.RESEARCH.value == "research"
    assert IntentKind.COMMAND.value == "command"
    assert IntentKind.CHAT.value == "chat"
    assert IntentKind.CLARIFY.value == "clarify"


def test_modifier_kind_values():
    assert ModifierKind.ADD.value == "add"
    assert ModifierKind.EXCLUDE.value == "exclude"
    assert ModifierKind.PRE_CHECK.value == "pre_check"
    assert ModifierKind.PRIORITY.value == "priority"
    assert ModifierKind.SWITCH_TO.value == "switch_to"
    assert ModifierKind.MODIFY.value == "modify"


def test_intent_construction():
    i = Intent(kind=IntentKind.RESEARCH, payload={"topic": "wheat rust"}, confidence=0.9)
    assert i.kind == IntentKind.RESEARCH
    assert i.payload["topic"] == "wheat rust"
    assert i.confidence == 0.9


def test_modifier_construction():
    m = Modifier(kind=ModifierKind.PRE_CHECK, value="wifi_on")
    assert m.kind == ModifierKind.PRE_CHECK
    assert m.value == "wifi_on"


def test_parsed_utterance_serialization():
    u = ParsedUtterance(
        raw="yes and also add voice activation",
        primary=Intent(kind=IntentKind.AFFIRM, payload={}, confidence=0.95),
        modifiers=[Modifier(kind=ModifierKind.ADD, value="voice_activation")],
        tone="casual",
    )
    d = u.to_dict()
    assert d["raw"] == "yes and also add voice activation"
    assert d["primary"]["kind"] == "affirm"
    assert d["modifiers"][0]["kind"] == "add"
    assert d["tone"] == "casual"


def test_execution_plan_construction():
    plan = ExecutionPlan(
        steps=[{"action": "research", "args": {"topic": "x"}}],
        pre_checks=["wifi_on"],
        rationale="user asked to research wheat after confirming wifi",
    )
    assert len(plan.steps) == 1
    assert "wifi_on" in plan.pre_checks
    assert plan.rationale.startswith("user")
