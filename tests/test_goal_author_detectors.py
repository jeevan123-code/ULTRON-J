"""Tests for goal_author pure detectors + safety classifier."""
from goal_author import (
    propose, classify_safety,
    _detect_repeated_failure, _detect_knowledge_gap,
    REPEATED_FAILURE_THRESHOLD, KNOWLEDGE_GAP_THRESHOLD,
)
from goal_author_types import GoalProposal, SafetyTier


# ── repeated_failure ──────────────────────────────────────────────────────
def test_repeated_failure_fires_at_threshold():
    obs = {"failure_counts": {"weather_fetch": REPEATED_FAILURE_THRESHOLD}}
    props = _detect_repeated_failure(obs)
    assert len(props) == 1
    assert props[0].trigger == "repeated_failure"
    assert props[0].subject == "weather_fetch"
    assert props[0].category == "research"


def test_repeated_failure_ignored_below_threshold():
    obs = {"failure_counts": {"x": REPEATED_FAILURE_THRESHOLD - 1}}
    assert _detect_repeated_failure(obs) == []


def test_repeated_failure_empty_when_no_data():
    assert _detect_repeated_failure({}) == []


# ── knowledge_gap ─────────────────────────────────────────────────────────
def test_knowledge_gap_fires_on_recurring_unknown_topic():
    obs = {
        "recent_topics": ["graphql"] * KNOWLEDGE_GAP_THRESHOLD,
        "known_topics": ["python", "flask"],
    }
    props = _detect_knowledge_gap(obs)
    assert any(p.subject == "graphql" and p.trigger == "knowledge_gap"
               for p in props)


def test_knowledge_gap_suppressed_when_topic_is_known():
    obs = {
        "recent_topics": ["python"] * (KNOWLEDGE_GAP_THRESHOLD + 2),
        "known_topics": ["python"],
    }
    assert _detect_knowledge_gap(obs) == []


def test_knowledge_gap_extracts_from_raw_utterances():
    # Raw sentences (contain spaces) -> tokeniser path; stopwords dropped.
    obs = {
        "recent_topics": [
            "how does kubernetes scaling work",
            "kubernetes networking question",
            "debugging kubernetes pods",
        ],
        "known_topics": [],
    }
    subjects = {p.subject for p in _detect_knowledge_gap(obs)}
    assert "kubernetes" in subjects
    assert "how" not in subjects  # stopword filtered


# ── propose orders by confidence ──────────────────────────────────────────
def test_propose_sorts_by_confidence_desc():
    obs = {
        "failure_counts": {"deploy": 10},                     # high confidence
        "recent_topics": ["rust"] * KNOWLEDGE_GAP_THRESHOLD,  # lower
        "known_topics": [],
    }
    props = propose(obs)
    assert len(props) >= 2
    assert props == sorted(props, key=lambda p: p.confidence, reverse=True)


# ── safety classifier ─────────────────────────────────────────────────────
def test_research_is_green():
    p = GoalProposal(title="Research X", description="read about X",
                     rationale="", trigger="knowledge_gap", subject="x",
                     category="research")
    assert classify_safety(p) == SafetyTier.GREEN


def test_automate_is_amber():
    p = GoalProposal(title="Automate the rename flow", description="",
                     rationale="", trigger="recurring_manual_task",
                     subject="rename", category="automate")
    assert classify_safety(p) == SafetyTier.AMBER


def test_destructive_keyword_forces_red():
    p = GoalProposal(title="Research how to delete old logs",
                     description="might rm -rf caches", rationale="",
                     trigger="housekeeping", subject="logs", category="research")
    assert classify_safety(p) == SafetyTier.RED
