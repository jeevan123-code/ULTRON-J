"""Tests for consent_types."""
from consent_types import ConsentMode


def test_consent_mode_values():
    assert ConsentMode.HANDS_ON.value == "hands_on"
    assert ConsentMode.VOICE_ONLY.value == "voice_only"
    assert ConsentMode.DECLINE.value == "decline"
    assert ConsentMode.NONE.value == "none"


def test_consent_mode_membership():
    assert ConsentMode("hands_on") == ConsentMode.HANDS_ON
    assert ConsentMode("voice_only") == ConsentMode.VOICE_ONLY
