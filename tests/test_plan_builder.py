"""Tests for plan_builder — utterance -> chained ExecutionPlan."""
import pytest

import plan_builder
from intent_types import ExecutionPlan


def _actions(plan: ExecutionPlan):
    return [s.get("action") for s in plan.steps]


def test_empty_utterance_returns_empty_plan():
    plan = plan_builder.build_from_utterance("")
    assert isinstance(plan, ExecutionPlan)
    assert plan.steps == []


def test_unknown_utterance_returns_empty_plan():
    plan = plan_builder.build_from_utterance("xyzzy nonsense words")
    assert plan.steps == []


def test_pure_research_utterance():
    plan = plan_builder.build_from_utterance("research GraphQL adoption")
    assert _actions(plan) == ["research"]
    assert plan.steps[0]["args"]["topic"]


def test_research_and_alert_chain():
    plan = plan_builder.build_from_utterance(
        "research AAPL halt and tell me on telegram"
    )
    assert _actions(plan) == ["research", "alert"]
    alert_args = plan.steps[1]["args"]
    assert "{{prev." in alert_args.get("message", "")


def test_research_and_announce_chain():
    plan = plan_builder.build_from_utterance(
        "research climate report then read it to me"
    )
    assert _actions(plan) == ["research", "announce"]


def test_look_and_announce_chain():
    plan = plan_builder.build_from_utterance(
        "look at the door and tell me who's there"
    )
    assert _actions(plan) == ["look", "announce"]
    assert "{{prev." in plan.steps[1]["args"]["text"]


def test_brief_me_utterance():
    plan = plan_builder.build_from_utterance("brief me now")
    assert _actions(plan) == ["briefing"]
    assert "voice" in plan.steps[0]["args"].get("channels", [])


def test_scenario_trigger_phrase():
    plan = plan_builder.build_from_utterance("activate house party protocol")
    assert _actions(plan) == ["scenario"]
    assert plan.steps[0]["args"]["name"] == "house_party"


def test_bedtime_scenario_phrase():
    plan = plan_builder.build_from_utterance("bedtime")
    assert _actions(plan) == ["scenario"]
    assert plan.steps[0]["args"]["name"] == "bedtime"


def test_case_insensitive_matching():
    plan_lower = plan_builder.build_from_utterance("research X and tell me")
    plan_upper = plan_builder.build_from_utterance("RESEARCH X AND TELL ME")
    assert _actions(plan_lower) == _actions(plan_upper)


def test_rationale_records_utterance():
    plan = plan_builder.build_from_utterance("research Tesla earnings")
    assert "Tesla" in plan.rationale or "tesla" in plan.rationale.lower()
