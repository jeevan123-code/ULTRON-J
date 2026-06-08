"""Tests for tone_modulator.modulate."""
import pytest

from tone_modulator import modulate
from mood_types import MoodState


# Passthrough / default

def test_empty_input_returns_empty():
    assert modulate("") == ""
    assert modulate(None) == ""


def test_passthrough_with_no_mood_or_privacy():
    text = "Here is the weather report for today."
    assert modulate(text) == text


def test_neutral_mood_does_not_rewrite():
    text = "Sir, here's what I found about the wheat disease."
    assert modulate(text, mood=MoodState.NEUTRAL) == text


# Mood: TIRED prepends a soft preamble

def test_tired_mood_adds_soft_preamble():
    text = "The build finished."
    out = modulate(text, mood=MoodState.TIRED)
    assert out.startswith("Take your time, sir.")
    assert "The build finished." in out


def test_tired_does_not_double_prepend():
    out1 = modulate("X", mood=MoodState.TIRED)
    out2 = modulate(out1, mood=MoodState.TIRED)
    assert out2.count("Take your time") == 1


# Mood: FRUSTRATED drops filler

def test_frustrated_drops_sir_prefix():
    out = modulate("Sir, the file is corrupted.", mood=MoodState.FRUSTRATED)
    assert not out.lower().startswith("sir,")
    assert "file is corrupted" in out


def test_frustrated_drops_heres_what_i_found_prefix():
    out = modulate("Here's what I found: the disk is full.", mood=MoodState.FRUSTRATED)
    assert "here's what i found" not in out.lower()
    assert "disk is full" in out


def test_frustrated_no_filler_left_unchanged():
    assert modulate("Build failed.", mood=MoodState.FRUSTRATED) == "Build failed."


# Privacy: secret redaction

@pytest.mark.parametrize("privacy_mode", ["stranger_present", "professional"])
def test_redacts_openai_key_when_stranger_or_pro(privacy_mode):
    text = "The key is sk-1234567890abcdefABCDEF111222."
    out = modulate(text, privacy_mode=privacy_mode)
    assert "sk-1234567890abcdef" not in out
    assert "[redacted]" in out


@pytest.mark.parametrize("privacy_mode", ["stranger_present", "professional"])
def test_redacts_bearer_token(privacy_mode):
    text = "Auth header is Bearer eyJhbGciOiJIUzI1NiIsInR5cCI."
    out = modulate(text, privacy_mode=privacy_mode)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI" not in out
    assert "[redacted]" in out


@pytest.mark.parametrize("privacy_mode", ["stranger_present", "professional"])
def test_redacts_password_assignment(privacy_mode):
    text = "password=hunter2 and other stuff"
    out = modulate(text, privacy_mode=privacy_mode)
    assert "hunter2" not in out


@pytest.mark.parametrize("privacy_mode", ["stranger_present", "professional"])
def test_redacts_local_home_path(privacy_mode):
    text = "Open /home/jeevan/secret.txt to verify."
    out = modulate(text, privacy_mode=privacy_mode)
    assert "/home/jeevan/secret.txt" not in out
    assert "[redacted]" in out


def test_does_not_redact_in_private_or_family_modes():
    text = "The key is sk-1234567890abcdefABCDEF111222."
    assert modulate(text, privacy_mode="private") == text
    assert modulate(text, privacy_mode="family") == text
    assert modulate(text, privacy_mode="friends") == text


# Combined: privacy + mood

def test_redaction_and_tired_preamble_compose():
    text = "Your password=hunter2 needs rotation."
    out = modulate(text, mood=MoodState.TIRED, privacy_mode="stranger_present")
    assert out.startswith("Take your time, sir.")
    assert "hunter2" not in out


def test_redaction_runs_even_when_frustrated():
    text = "Sir, the password=hunter2 is wrong."
    out = modulate(text, mood=MoodState.FRUSTRATED, privacy_mode="professional")
    assert "hunter2" not in out
    assert not out.lower().startswith("sir,")
