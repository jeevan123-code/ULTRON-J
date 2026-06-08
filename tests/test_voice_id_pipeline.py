"""Tests for voice_id_pipeline — orchestrate audio -> identify -> record/stranger."""
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

import voice_id_pipeline as p
import person_registry as reg
import room_awareness as ra
import stranger_offer as so
from person_types import Person, Relation


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    ra._reset_for_test()
    so._reset_for_test()
    yield
    ra._reset_for_test()
    so._reset_for_test()


def _unit(seed: int, length: int = 8) -> list:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=length)
    return list(v / np.linalg.norm(v))


def test_pipeline_records_known_voice():
    vp = _unit(42)
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=vp, enrolled_at=1.0))
    with patch.object(p, "_get_embedding", return_value=np.array(vp)):
        result = p.process_audio_clip("/tmp/ravi.wav")
    assert result["action"] == "recorded"
    assert result["name"] == "Ravi"
    assert ra.who_is_in_the_room() == ["Ravi"]


def test_pipeline_emits_stranger_offer_for_unknown_voice():
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=_unit(42), enrolled_at=1.0))
    speak = MagicMock()
    with patch.object(p, "_get_embedding", return_value=np.array(_unit(99))), \
         patch.object(so, "_speak", speak):
        result = p.process_audio_clip("/tmp/unknown.wav")
    assert result["action"] == "stranger_offer"
    assert so.peek_pending() is not None
    speak.assert_called_once()
    assert "_stranger" in ra.who_is_in_the_room()


def test_pipeline_handles_embedding_failure_gracefully():
    with patch.object(p, "_get_embedding", return_value=None):
        result = p.process_audio_clip("/tmp/bad.wav")
    assert result["action"] == "skipped"
    assert result.get("reason") == "no_embedding"
    assert ra.who_is_in_the_room() == []


def test_pipeline_skip_returns_when_audio_path_empty():
    result = p.process_audio_clip("")
    assert result["action"] == "skipped"
    assert result.get("reason") == "no_audio_path"


def test_pipeline_does_not_speak_when_stranger_offer_rate_limited():
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=_unit(42), enrolled_at=1.0))
    speak = MagicMock()
    with patch.object(p, "_get_embedding", return_value=np.array(_unit(99))), \
         patch.object(so, "_speak", speak):
        p.process_audio_clip("/tmp/u1.wav")
        p.process_audio_clip("/tmp/u2.wav")
    speak.assert_called_once()
