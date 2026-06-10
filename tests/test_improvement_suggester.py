"""Tests for improvement_suggester — pure pattern detection."""
import pytest

from improvement_suggester import analyze, BATCH_RENAME_THRESHOLD, MORNING_ROUTINE_WINDOW_SECONDS, MORNING_ROUTINE_MIN_LAUNCHES
from improvement_types import Suggestion
from action_types import ActionEvent, ActionKind


def _rename(ts: float, target: str):
    return ActionEvent(ts=ts, kind=ActionKind.FILE_RENAME, target=target)


def _launch(ts: float, app: str):
    return ActionEvent(ts=ts, kind=ActionKind.APP_LAUNCH, target=app)


def _click(ts: float, target: str = "btn"):
    return ActionEvent(ts=ts, kind=ActionKind.CLICK, target=target)


def test_empty_input_returns_no_suggestions():
    assert analyze([]) == []


def test_random_mixed_actions_returns_nothing():
    events = [
        _click(1.0), _rename(2.0, "a"), _launch(3.0, "zoom"),
        _click(4.0), _rename(5.0, "b"),
    ]
    assert analyze(events) == []


def test_five_file_renames_in_a_row_suggests_batch_rename():
    events = [_rename(float(i), f"f{i}.txt") for i in range(BATCH_RENAME_THRESHOLD)]
    suggestions = analyze(events)
    kinds = [s.kind for s in suggestions]
    assert "batch_rename" in kinds


def test_batch_rename_suggestion_carries_supporting_events():
    events = [_rename(float(i), f"f{i}.txt") for i in range(BATCH_RENAME_THRESHOLD)]
    suggestions = analyze(events)
    s = next(x for x in suggestions if x.kind == "batch_rename")
    assert isinstance(s, Suggestion)
    assert len(s.supporting_events) >= BATCH_RENAME_THRESHOLD
    assert s.template


def test_four_file_renames_does_not_trigger_batch_rename():
    events = [_rename(float(i), f"f{i}.txt") for i in range(BATCH_RENAME_THRESHOLD - 1)]
    assert analyze(events) == []


def test_three_identical_app_launches_in_window_suggests_morning_routine():
    events = [
        _launch(0.0, "zoom"),
        _launch(5.0, "zoom"),
        _launch(10.0, "zoom"),
    ]
    suggestions = analyze(events)
    assert any(s.kind == "morning_routine" for s in suggestions)


def test_app_launches_outside_window_do_not_trigger():
    events = [
        _launch(0.0, "zoom"),
        _launch(MORNING_ROUTINE_WINDOW_SECONDS + 5, "zoom"),
        _launch(2 * MORNING_ROUTINE_WINDOW_SECONDS + 10, "zoom"),
    ]
    assert not any(s.kind == "morning_routine" for s in analyze(events))


def test_different_apps_do_not_trigger_morning_routine():
    events = [
        _launch(0.0, "zoom"),
        _launch(5.0, "slack"),
        _launch(10.0, "notes"),
    ]
    assert not any(s.kind == "morning_routine" for s in analyze(events))
