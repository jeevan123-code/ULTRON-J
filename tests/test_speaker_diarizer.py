"""Tests for speaker_diarizer — cosine-similarity identification."""
import os
import numpy as np
import pytest

import speaker_diarizer as sd
import person_registry as reg
from person_types import Person, Relation, RecognitionResult


@pytest.fixture(autouse=True)
def _tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    yield


def _unit_vec(seed: int, length: int = 8) -> list:
    """Build a deterministic non-zero vector for testing."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=length)
    return list(v / np.linalg.norm(v))


def test_identify_speaker_no_registered_persons_returns_no_match():
    embedding = _unit_vec(1)
    result = sd.identify_speaker(embedding)
    assert isinstance(result, RecognitionResult)
    assert result.matched is False
    assert result.similarity == 0.0


def test_identify_speaker_matches_exact_voiceprint():
    vp = _unit_vec(42)
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=vp, enrolled_at=100.0))
    result = sd.identify_speaker(vp)
    assert result.matched is True
    assert result.name == "Ravi"
    assert result.similarity > 0.999


def test_identify_speaker_unknown_voice_returns_no_match():
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=_unit_vec(42), enrolled_at=100.0))
    unrelated = _unit_vec(99)
    result = sd.identify_speaker(unrelated, threshold=0.75)
    assert result.matched is False
    assert result.name is None
    assert 0.0 <= result.similarity <= 1.0


def test_identify_speaker_picks_highest_similarity_when_multiple_pass():
    vp_a = _unit_vec(11)
    vp_b = _unit_vec(22)
    reg.register(Person(name="A", relation=Relation.FRIEND,
                        voiceprint=vp_a, enrolled_at=1.0))
    reg.register(Person(name="B", relation=Relation.FRIEND,
                        voiceprint=vp_b, enrolled_at=2.0))
    result = sd.identify_speaker(vp_a, threshold=0.5)
    assert result.name == "A"


def test_identify_speaker_respects_custom_threshold():
    vp = _unit_vec(7)
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=vp, enrolled_at=100.0))
    near = list(np.array(vp) * 0.99)
    assert sd.identify_speaker(near, threshold=0.95).matched is True
    assert sd.identify_speaker(near, threshold=0.999999).matched is False


def test_identify_speaker_handles_numpy_input():
    vp = _unit_vec(3)
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=vp, enrolled_at=100.0))
    result = sd.identify_speaker(np.array(vp))
    assert result.matched is True
    assert result.name == "Ravi"


def test_identify_speaker_empty_embedding_returns_no_match():
    result = sd.identify_speaker([])
    assert result.matched is False
    assert result.similarity == 0.0
