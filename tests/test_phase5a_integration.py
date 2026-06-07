"""End-to-end Phase 5a: register -> identify -> room awareness."""
import numpy as np
import pytest

import person_registry as reg
import speaker_diarizer as sd
import room_awareness as ra
from person_types import Person, Relation


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    ra._reset_for_test()
    yield
    ra._reset_for_test()


def _unit(seed: int, length: int = 16) -> list:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=length)
    return list(v / np.linalg.norm(v))


def test_full_register_identify_record_flow():
    jeevan_vp = _unit(1)
    ravi_vp = _unit(2)
    reg.register(Person(name="Jeevan", relation=Relation.SELF,
                        voiceprint=jeevan_vp, enrolled_at=1.0))
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=ravi_vp, enrolled_at=2.0))

    result = sd.identify_speaker(jeevan_vp)
    assert result.matched is True
    assert result.name == "Jeevan"

    ra.record_voice(result.name, ts=100.0)
    assert ra.who_is_in_the_room(now=200.0) == ["Jeevan"]

    result2 = sd.identify_speaker(ravi_vp)
    assert result2.name == "Ravi"
    ra.record_voice(result2.name, ts=150.0)
    assert sorted(ra.who_is_in_the_room(now=200.0)) == ["Jeevan", "Ravi"]


def test_stranger_voice_is_not_recorded():
    reg.register(Person(name="Jeevan", relation=Relation.SELF,
                        voiceprint=_unit(1), enrolled_at=1.0))
    result = sd.identify_speaker(_unit(99))
    assert result.matched is False

    if result.matched:
        ra.record_voice(result.name)
    assert ra.who_is_in_the_room() == []


def test_room_awareness_forgets_stale_voices():
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=_unit(2), enrolled_at=1.0))
    ra.record_voice("Ravi", ts=100.0)
    assert ra.who_is_in_the_room(now=1100.0, within_seconds=300) == []
