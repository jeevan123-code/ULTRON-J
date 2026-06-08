"""Mood Tracker — deterministic mood inference.

Hour buckets:
    [22, 23, 0..5]              -> TIRED       (reason: late_hour)
    [6..11]                     -> FOCUSED     (reason: morning)
    [12..16]                    -> NEUTRAL     (reason: afternoon)
    [17..21]                    -> RELAXED     (reason: evening)

Struggle override (always wins):
    recent_struggles >= 2       -> FRUSTRATED  (reason: struggle_override)
"""
import datetime
from typing import Optional

from mood_types import MoodReading, MoodState


_STRUGGLE_THRESHOLD = 2


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _bucket_for_hour(hour: int):
    """Return (MoodState, reason) for the given 0..23 hour."""
    if hour >= 22 or hour <= 5:
        return MoodState.TIRED, "late_hour"
    if 6 <= hour <= 11:
        return MoodState.FOCUSED, "morning"
    if 12 <= hour <= 16:
        return MoodState.NEUTRAL, "afternoon"
    return MoodState.RELAXED, "evening"


def current_mood_reading(now: Optional[datetime.datetime] = None,
                         recent_struggles: int = 0) -> MoodReading:
    """Return a full MoodReading snapshot."""
    if now is None:
        now = _now()
    hour = now.hour
    struggles = max(0, int(recent_struggles))

    if struggles >= _STRUGGLE_THRESHOLD:
        return MoodReading(
            state=MoodState.FRUSTRATED,
            hour=hour,
            recent_struggles=struggles,
            reason="struggle_override",
        )

    state, reason = _bucket_for_hour(hour)
    return MoodReading(
        state=state,
        hour=hour,
        recent_struggles=struggles,
        reason=reason,
    )


def current_mood(now: Optional[datetime.datetime] = None,
                 recent_struggles: int = 0) -> MoodState:
    """Convenience wrapper returning only the state."""
    return current_mood_reading(now=now, recent_struggles=recent_struggles).state
