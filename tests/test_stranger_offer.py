"""Tests for stranger_offer — pending state + voice prompt + enrollment dispatch."""
from unittest.mock import patch, MagicMock
import pytest

import stranger_offer as so
import person_registry as reg
from person_types import Person, Relation
from voice_id_types import StrangerEvent


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    so._reset_for_test()
    yield
    so._reset_for_test()


def _event() -> StrangerEvent:
    return StrangerEvent(
        embedding=[0.1, 0.2, 0.3, 0.4],
        audio_path="/tmp/clip.wav",
        detected_at=100.0,
    )


def test_handle_stranger_speaks_polite_prompt():
    speak = MagicMock()
    with patch.object(so, "_speak", speak):
        ok = so.handle_stranger(_event())
    assert ok is True
    speak.assert_called_once()
    text = speak.call_args[0][0].lower()
    assert "different voice" in text


def test_handle_stranger_sets_pending():
    with patch.object(so, "_speak", MagicMock()):
        so.handle_stranger(_event())
    p = so.peek_pending()
    assert p is not None
    assert p["audio_path"] == "/tmp/clip.wav"
    assert p["embedding"] == [0.1, 0.2, 0.3, 0.4]


def test_handle_stranger_rate_limited():
    speak = MagicMock()
    with patch.object(so, "_speak", speak):
        so.handle_stranger(_event())
        so.handle_stranger(_event())
    speak.assert_called_once()


def test_handle_stranger_after_rate_limit_speaks_again():
    speak = MagicMock()
    with patch.object(so, "_speak", speak):
        so.handle_stranger(_event())
        so._last_offer_at -= so._RATE_LIMIT_SECONDS + 1
        so.handle_stranger(_event())
    assert speak.call_count == 2


def test_confirm_stranger_resolved_enrolls_person():
    with patch.object(so, "_speak", MagicMock()):
        so.handle_stranger(_event())
        result = so.confirm_stranger("That's Ravi, my brother")
    assert result["enrolled"] is True
    assert result["name"] == "Ravi"
    assert result["relation"] == "family"
    p = reg.get("Ravi")
    assert p is not None
    assert p.relation == Relation.FAMILY
    assert p.voiceprint == [0.1, 0.2, 0.3, 0.4]
    assert so.peek_pending() is None


def test_confirm_stranger_skip_clears_pending_without_enrolling():
    with patch.object(so, "_speak", MagicMock()):
        so.handle_stranger(_event())
        result = so.confirm_stranger("skip it")
    assert result["enrolled"] is False
    assert result.get("reason") == "skipped"
    assert so.peek_pending() is None
    assert reg.list_all() == []


def test_confirm_stranger_ambiguous_keeps_pending():
    with patch.object(so, "_speak", MagicMock()):
        so.handle_stranger(_event())
        result = so.confirm_stranger("what's the weather today")
    assert result["enrolled"] is False
    assert result.get("reason") == "unresolved"
    assert so.peek_pending() is not None


def test_confirm_stranger_no_pending_returns_noop():
    result = so.confirm_stranger("that's Ravi, my brother")
    assert result["enrolled"] is False
    assert result.get("reason") == "no_pending"
