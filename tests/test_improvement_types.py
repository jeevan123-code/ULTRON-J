"""Tests for improvement_types — Suggestion dataclass."""
import pytest

from improvement_types import Suggestion
from action_types import ActionEvent, ActionKind


def _ev(ts: float, target: str = "notes.txt"):
    return ActionEvent(ts=ts, kind=ActionKind.FILE_RENAME, target=target)


def test_suggestion_construction():
    events = [_ev(1.0), _ev(2.0)]
    s = Suggestion(
        kind="batch_rename",
        summary="You renamed 2 files — want a script?",
        template="batch_rename_script",
        supporting_events=events,
        confidence=0.85,
    )
    assert s.kind == "batch_rename"
    assert s.confidence == 0.85
    assert s.supporting_events == events


def test_suggestion_to_dict_roundtrip():
    s = Suggestion(
        kind="morning_routine",
        summary="3 app launches in 30s — make a shortcut?",
        template="morning_routine_script",
        supporting_events=[_ev(1.0, "zoom"), _ev(2.0, "zoom")],
        confidence=0.6,
    )
    d = s.to_dict()
    assert d["kind"] == "morning_routine"
    assert d["confidence"] == 0.6
    assert isinstance(d["supporting_events"], list)
    assert d["supporting_events"][0]["target"] == "zoom"


def test_suggestion_confidence_clamped_to_0_1():
    s = Suggestion(
        kind="x", summary="x", template="x",
        supporting_events=[], confidence=2.5,
    )
    assert s.confidence == 1.0

    s2 = Suggestion(
        kind="x", summary="x", template="x",
        supporting_events=[], confidence=-0.1,
    )
    assert s2.confidence == 0.0
