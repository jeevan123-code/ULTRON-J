"""Tests for mood_types."""
from mood_types import MoodState, MoodReading


def test_mood_state_values():
    assert MoodState.TIRED.value == "tired"
    assert MoodState.FOCUSED.value == "focused"
    assert MoodState.NEUTRAL.value == "neutral"
    assert MoodState.RELAXED.value == "relaxed"
    assert MoodState.FRUSTRATED.value == "frustrated"


def test_mood_reading_construction():
    r = MoodReading(state=MoodState.TIRED, hour=23, recent_struggles=0, reason="late_hour")
    assert r.state == MoodState.TIRED
    assert r.hour == 23
    assert r.recent_struggles == 0
    assert r.reason == "late_hour"


def test_mood_reading_to_dict():
    r = MoodReading(state=MoodState.FRUSTRATED, hour=14, recent_struggles=3, reason="struggle_override")
    d = r.to_dict()
    assert d == {
        "state": "frustrated",
        "hour": 14,
        "recent_struggles": 3,
        "reason": "struggle_override",
    }
