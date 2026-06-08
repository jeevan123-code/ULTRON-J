"""Tests for mood_tracker.current_mood and current_mood_reading."""
import datetime
import pytest

import mood_tracker as mt
from mood_types import MoodState


def _at(hour: int) -> datetime.datetime:
    """Return a datetime on a fixed date at the given hour."""
    return datetime.datetime(2026, 6, 8, hour, 0, 0)


@pytest.mark.parametrize("hour", [22, 23, 0, 3, 5])
def test_tired_at_late_or_early_hours(hour):
    r = mt.current_mood_reading(now=_at(hour))
    assert r.state == MoodState.TIRED
    assert r.reason == "late_hour"


@pytest.mark.parametrize("hour", [6, 8, 11])
def test_focused_in_morning(hour):
    r = mt.current_mood_reading(now=_at(hour))
    assert r.state == MoodState.FOCUSED
    assert r.reason == "morning"


@pytest.mark.parametrize("hour", [12, 14, 16])
def test_neutral_in_afternoon(hour):
    r = mt.current_mood_reading(now=_at(hour))
    assert r.state == MoodState.NEUTRAL
    assert r.reason == "afternoon"


@pytest.mark.parametrize("hour", [17, 19, 21])
def test_relaxed_in_evening(hour):
    r = mt.current_mood_reading(now=_at(hour))
    assert r.state == MoodState.RELAXED
    assert r.reason == "evening"


def test_struggle_override_beats_time_signal():
    r = mt.current_mood_reading(now=_at(10), recent_struggles=3)
    assert r.state == MoodState.FRUSTRATED
    assert r.reason == "struggle_override"


def test_struggle_threshold_is_two():
    r1 = mt.current_mood_reading(now=_at(14), recent_struggles=1)
    assert r1.state == MoodState.NEUTRAL
    r2 = mt.current_mood_reading(now=_at(14), recent_struggles=2)
    assert r2.state == MoodState.FRUSTRATED


def test_negative_struggle_count_treated_as_zero():
    r = mt.current_mood_reading(now=_at(14), recent_struggles=-5)
    assert r.state == MoodState.NEUTRAL


def test_current_mood_returns_just_the_state():
    state = mt.current_mood(now=_at(10))
    assert state == MoodState.FOCUSED


def test_current_mood_uses_default_now_when_not_provided(monkeypatch):
    monkeypatch.setattr(mt, "_now", lambda: _at(14))
    state = mt.current_mood()
    assert state == MoodState.NEUTRAL


def test_hour_field_reflects_input_hour():
    r = mt.current_mood_reading(now=_at(17))
    assert r.hour == 17
