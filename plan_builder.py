"""Phase 10 plan builder — utterance -> chained ExecutionPlan.

Pure rule-based for now. Each pattern (a compiled regex on the lowered
utterance) maps to a step generator: a function that returns a list of
chain steps. Patterns are tried in order; the FIRST match wins, so more
specific patterns must come before general ones.

This is deliberately rule-based rather than LLM-driven so it is:
  * Deterministic and unit-testable
  * Fast (no network round-trip)
  * Safe (no hallucinated step types)

A future LLM tier can wrap this: if `build_from_utterance` returns an
empty plan, fall through to a model. For now, an empty result means
"no plan — let the existing voice_engine fast-path handle it."
"""
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Pattern

from intent_types import ExecutionPlan


@dataclass
class _Pattern:
    regex: Pattern[str]
    builder: Callable[[re.Match], List[dict]]


# ---- step generators ----

def _topic_from(match: re.Match, group: int = 1) -> str:
    return (match.group(group) or "").strip()


def _research_and_alert(match: re.Match) -> List[dict]:
    topic = _topic_from(match)
    return [
        {"action": "research", "args": {"topic": topic}},
        {"action": "alert", "args": {
            "message": f"Research on {topic}: {{{{prev.summary}}}}",
            "priority": "normal",
        }, "continue_on_failure": True},
    ]


def _research_and_announce(match: re.Match) -> List[dict]:
    topic = _topic_from(match)
    return [
        {"action": "research", "args": {"topic": topic}},
        {"action": "announce", "args": {
            "text": f"Sir, here's what I found on {topic}: {{{{prev.summary}}}}",
        }, "continue_on_failure": True},
    ]


def _research_only(match: re.Match) -> List[dict]:
    return [{"action": "research", "args": {"topic": _topic_from(match)}}]


def _look_and_announce(_match: re.Match) -> List[dict]:
    return [
        {"action": "look"},
        {"action": "announce", "args": {
            "text": "Sir, I see {{prev.faces}} person(s) in front of the camera.",
        }, "continue_on_failure": True},
    ]


def _briefing(_match: re.Match) -> List[dict]:
    return [{"action": "briefing", "args": {"channels": ["voice", "telegram"]}}]


def _scenario(name: str) -> Callable[[re.Match], List[dict]]:
    def _build(_match: re.Match) -> List[dict]:
        return [{"action": "scenario", "args": {"name": name}}]
    return _build


# ---- pattern table (specific first, general last) ----

_PATTERNS: List[_Pattern] = [
    # Scenario triggers — match BEFORE generic verbs
    _Pattern(re.compile(r"\b(house party|lockdown mode)\b"), _scenario("house_party")),
    _Pattern(re.compile(r"\b(bedtime|good night|going to sleep)\b"), _scenario("bedtime")),
    _Pattern(re.compile(r"\b(get me ready|prep for the call)\b"), _scenario("get_ready_for_call")),

    # Briefing
    _Pattern(re.compile(r"\bbrief me\b"), _briefing),

    # Vision chain
    _Pattern(re.compile(r"\blook (at )?(the )?(door|camera|outside|room)\b"), _look_and_announce),
    _Pattern(re.compile(r"\b(who|what)('s| is) (there|at the door|outside)\b"), _look_and_announce),

    # Research + alert (telegram-ish phrasing)
    _Pattern(
        re.compile(r"\bresearch (.+?) and (tell|message|alert|notify) me\b"),
        _research_and_alert,
    ),
    _Pattern(
        re.compile(r"\bresearch (.+?) and (send|push) (it )?to (telegram|my phone)\b"),
        _research_and_alert,
    ),

    # Research + announce (voice phrasing)
    _Pattern(
        re.compile(r"\bresearch (.+?) (then |and )?(read|say|speak|announce)( it)?( to me)?\b"),
        _research_and_announce,
    ),

    # Pure research (most general — last)
    _Pattern(re.compile(r"\bresearch (.+?)$"), _research_only),
    _Pattern(re.compile(r"\bresearch (.+?)\b"), _research_only),
]


def build_from_utterance(utterance: str) -> ExecutionPlan:
    """Turn a user utterance into a multi-step ExecutionPlan."""
    if not utterance or not utterance.strip():
        return ExecutionPlan(steps=[], pre_checks=[], rationale="")
    text = utterance.lower().strip()

    for pat in _PATTERNS:
        m = pat.regex.search(text)
        if m:
            steps = pat.builder(m)
            return ExecutionPlan(
                steps=steps, pre_checks=[],
                rationale=f"plan_builder matched: {utterance}",
            )

    return ExecutionPlan(steps=[], pre_checks=[], rationale="")
