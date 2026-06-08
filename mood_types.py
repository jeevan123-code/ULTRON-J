"""Phase 5c shared mood types."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class MoodState(str, Enum):
    """Inferred mood label.

    Values:
        TIRED      — late hours, low energy. Soften tone.
        FOCUSED    — morning hours, in flow. No interruptions.
        NEUTRAL    — workday afternoon, default behavior.
        RELAXED    — evening, casual chit-chat ok.
        FRUSTRATED — recent struggle events outweighed the time signal.
    """
    TIRED = "tired"
    FOCUSED = "focused"
    NEUTRAL = "neutral"
    RELAXED = "relaxed"
    FRUSTRATED = "frustrated"


@dataclass
class MoodReading:
    """Snapshot returned by mood_tracker.current_mood_reading()."""
    state: MoodState
    hour: int
    recent_struggles: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "hour": self.hour,
            "recent_struggles": self.recent_struggles,
            "reason": self.reason,
        }
