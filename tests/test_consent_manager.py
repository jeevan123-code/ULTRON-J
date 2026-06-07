"""Tests for consent_manager."""
import pytest
from consent_manager import parse_consent
from consent_types import ConsentMode


@pytest.mark.parametrize("text", [
    "yes you can",
    "go ahead, take over",
    "yes please take over",
    "do it",
    "yeah help me",
    "sure, fix it for me",
])
def test_parse_consent_hands_on(text):
    assert parse_consent(text) == ConsentMode.HANDS_ON


@pytest.mark.parametrize("text", [
    "yes, just tell me",
    "yes you can say your thought",
    "voice only please",
    "just tell me the solution",
    "tell me what to do",
    "yes but only describe it",
])
def test_parse_consent_voice_only(text):
    assert parse_consent(text) == ConsentMode.VOICE_ONLY


@pytest.mark.parametrize("text", [
    "no",
    "no thanks",
    "I got it",
    "skip it",
    "not now",
    "I don't need help",
])
def test_parse_consent_decline(text):
    assert parse_consent(text) == ConsentMode.DECLINE


@pytest.mark.parametrize("text", [
    "",
    "what's the weather like",
    "open chrome",
    "research wheat rust",
])
def test_parse_consent_none(text):
    assert parse_consent(text) == ConsentMode.NONE


def test_parse_consent_voice_only_beats_hands_on():
    """When BOTH 'yes' and 'tell me' appear, voice-only wins."""
    assert parse_consent("yes go ahead but just tell me") == ConsentMode.VOICE_ONLY
