"""Tests for plan_validator — catches malformed ExecutionPlans at build time."""
import pytest

from plan_validator import validate, ValidationIssue, SEVERITY_ERROR, SEVERITY_WARNING
from intent_types import ExecutionPlan


def _plan(*steps):
    return ExecutionPlan(steps=list(steps), pre_checks=[], rationale="test")


def test_valid_research_plan_returns_no_issues():
    plan = _plan({"action": "research", "args": {"topic": "AAPL"}})
    assert validate(plan) == []


def test_valid_multi_step_chain_returns_no_issues():
    plan = _plan(
        {"action": "research", "args": {"topic": "AAPL"}},
        {"action": "alert", "args": {"message": "done", "priority": "high"}},
    )
    assert validate(plan) == []


def test_empty_plan_emits_warning():
    plan = _plan()
    issues = validate(plan)
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_WARNING
    assert issues[0].step_index == -1
    assert "empty" in issues[0].message.lower()


def test_unknown_action_emits_error():
    plan = _plan({"action": "fly_to_moon", "args": {}})
    issues = validate(plan)
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_ERROR
    assert issues[0].step_index == 0
    assert "fly_to_moon" in issues[0].message


def test_missing_action_field_emits_error():
    plan = _plan({"args": {"topic": "x"}})
    issues = validate(plan)
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_ERROR
    assert "action" in issues[0].message.lower()


def test_research_missing_topic_emits_error():
    plan = _plan({"action": "research", "args": {}})
    issues = validate(plan)
    assert any(i.severity == SEVERITY_ERROR and "topic" in i.message.lower() for i in issues)


def test_alert_missing_message_emits_error():
    plan = _plan({"action": "alert", "args": {"priority": "high"}})
    issues = validate(plan)
    assert any(i.severity == SEVERITY_ERROR and "message" in i.message.lower() for i in issues)


def test_announce_missing_text_emits_error():
    plan = _plan({"action": "announce", "args": {}})
    issues = validate(plan)
    assert any(i.severity == SEVERITY_ERROR and "text" in i.message.lower() for i in issues)


def test_scenario_missing_name_emits_error():
    plan = _plan({"action": "scenario", "args": {}})
    issues = validate(plan)
    assert any(i.severity == SEVERITY_ERROR and "name" in i.message.lower() for i in issues)


def test_takeover_missing_all_known_args_emits_error():
    plan = _plan({"action": "takeover", "args": {"random": "x"}})
    issues = validate(plan)
    assert any(i.severity == SEVERITY_ERROR for i in issues)


def test_look_needs_no_args():
    """look is a special primitive — no args required."""
    plan = _plan({"action": "look"})
    assert validate(plan) == []


def test_briefing_needs_no_args():
    """briefing args have safe defaults."""
    plan = _plan({"action": "briefing"})
    assert validate(plan) == []


def test_both_conditional_flags_on_same_step_emits_error():
    plan = _plan({
        "action": "research", "args": {"topic": "x"},
        "if_prev_ok": True, "if_prev_failed": True,
    })
    issues = validate(plan)
    assert any(i.severity == SEVERITY_ERROR and "exclusive" in i.message.lower() for i in issues)


def test_if_prev_failed_on_first_step_emits_warning():
    plan = _plan({
        "action": "research", "args": {"topic": "x"},
        "if_prev_failed": True,
    })
    issues = validate(plan)
    assert any(i.severity == SEVERITY_WARNING and i.step_index == 0 for i in issues)


def test_multiple_issues_collected():
    plan = _plan(
        {"action": "research", "args": {}},   # missing topic
        {"action": "fake_action", "args": {}}, # unknown action
    )
    issues = validate(plan)
    assert len(issues) >= 2
    err_actions = {i.message.lower() for i in issues}
    assert any("topic" in m for m in err_actions)
    assert any("fake_action" in m for m in err_actions)


def test_validation_issue_to_dict_roundtrip():
    issue = ValidationIssue(severity="error", step_index=2, message="oops")
    d = issue.to_dict()
    assert d["severity"] == "error"
    assert d["step_index"] == 2
    assert d["message"] == "oops"
