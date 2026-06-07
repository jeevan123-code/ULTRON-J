"""Phase 3b consent mode enum."""
from enum import Enum


class ConsentMode(str, Enum):
    """User's response to a proactive help offer."""
    HANDS_ON = "hands_on"
    VOICE_ONLY = "voice_only"
    DECLINE = "decline"
    NONE = "none"
