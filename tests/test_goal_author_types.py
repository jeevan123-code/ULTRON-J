"""Tests for goal_author_types — GoalProposal + SafetyTier."""
from goal_author_types import GoalProposal, SafetyTier, _normalise


def test_dedup_key_is_computed_from_trigger_and_subject():
    p = GoalProposal(
        title="t", description="d", rationale="r",
        trigger="repeated_failure", subject="weather_fetch",
    )
    assert p.dedup_key == "repeated_failure:weather_fetch"


def test_dedup_key_stable_across_case_and_whitespace():
    a = GoalProposal(title="t", description="d", rationale="r",
                     trigger="knowledge_gap", subject="Quantum  Computing")
    b = GoalProposal(title="x", description="y", rationale="z",
                     trigger="knowledge_gap", subject="quantum computing")
    assert a.dedup_key == b.dedup_key


def test_explicit_dedup_key_is_respected():
    p = GoalProposal(title="t", description="d", rationale="r",
                     trigger="x", subject="y", dedup_key="custom")
    assert p.dedup_key == "custom"


def test_roundtrip_dict():
    p = GoalProposal(title="t", description="d", rationale="r",
                     trigger="knowledge_gap", subject="rust",
                     priority="high", confidence=0.8, category="research")
    assert GoalProposal.from_dict(p.to_dict()) == p


def test_safety_tiers_exist():
    assert {t.value for t in SafetyTier} == {"green", "amber", "red"}


def test_normalise():
    assert _normalise("  Foo   BAR ") == "foo bar"
