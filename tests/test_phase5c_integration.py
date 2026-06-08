"""End-to-end Phase 5c: mood inference + privacy_circle + tone_modulator."""
import datetime
import pytest

import mood_tracker as mt
import privacy_circle as pc
import person_registry as reg
import room_awareness as ra
from mood_types import MoodState
from person_types import Person, Relation
from tone_modulator import modulate


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    ra._reset_for_test()
    yield
    ra._reset_for_test()


def _at(hour: int) -> datetime.datetime:
    return datetime.datetime(2026, 6, 8, hour, 0, 0)


def test_full_stranger_present_at_late_night_redacts_and_softens():
    # Stranger is in the room AND it's late at night
    ra.record_voice("_stranger", ts=200.0)
    mode = pc.current_mode(now=300.0)
    assert mode == "stranger_present"

    mood = mt.current_mood(now=_at(23))
    assert mood == MoodState.TIRED

    raw = "Sir, the password=hunter2 unlocks /home/jeevan/vault.json."
    out = modulate(raw, mood=mood, privacy_mode=mode)

    assert out.startswith("Take your time, sir.")
    assert "hunter2" not in out
    assert "/home/jeevan/vault.json" not in out
    assert "[redacted]" in out


def test_private_room_during_focus_hours_leaves_text_alone():
    """No people in the room + morning focus -> raw passthrough."""
    mode = pc.current_mode(now=300.0)
    assert mode == "private"
    mood = mt.current_mood(now=_at(10))
    assert mood == MoodState.FOCUSED

    raw = "Here's what I found about the build."
    assert modulate(raw, mood=mood, privacy_mode=mode) == raw


def test_professional_present_during_struggle_terse_and_redacted():
    reg.register(Person(name="Tony", relation=Relation.PROFESSIONAL,
                        voiceprint=[0.1] * 8, enrolled_at=1.0))
    ra.record_voice("Tony", ts=200.0)
    mode = pc.current_mode(now=300.0)
    assert mode == "professional"

    mood = mt.current_mood(now=_at(14), recent_struggles=3)
    assert mood == MoodState.FRUSTRATED

    raw = "Sir, the api_KEY=abc123def456 has expired."
    out = modulate(raw, mood=mood, privacy_mode=mode)

    assert not out.lower().startswith("sir,")
    assert "abc123def456" not in out
    assert "[redacted]" in out


def test_family_present_leaves_secrets_visible_but_softens_when_tired():
    """Family is trusted; secrets stay. Late hour still softens tone."""
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=[0.1] * 8, enrolled_at=1.0))
    ra.record_voice("Ravi", ts=200.0)
    mode = pc.current_mode(now=300.0)
    assert mode == "family"
    mood = mt.current_mood(now=_at(23))

    raw = "The path is /home/jeevan/notes.txt."
    out = modulate(raw, mood=mood, privacy_mode=mode)
    assert "/home/jeevan/notes.txt" in out          # NOT redacted
    assert out.startswith("Take your time, sir.")
