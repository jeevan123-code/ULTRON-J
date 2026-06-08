"""End-to-end Phase 5b: audio -> identify -> stranger offer -> enroll -> privacy mode."""
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

import voice_id_pipeline as p
import person_registry as reg
import room_awareness as ra
import stranger_offer as so
import privacy_circle as pc
from person_types import Person, Relation


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    ra._reset_for_test()
    so._reset_for_test()
    yield
    ra._reset_for_test()
    so._reset_for_test()


def _unit(seed: int, length: int = 32) -> list:
    """32-dim unit vector — high enough dimension that two random seeds
    give cosine similarity well below the 0.75 threshold, avoiding flaky
    'unknown matches' in this end-to-end test."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=length)
    return list(v / np.linalg.norm(v))


def test_full_stranger_then_enrollment_then_privacy_shift():
    # 1. Jeevan is enrolled
    jeevan_vp = _unit(1)
    reg.register(Person(name="Jeevan", relation=Relation.SELF,
                        voiceprint=jeevan_vp, enrolled_at=1.0))

    # 2. Unknown voice (Ravi) arrives
    speak = MagicMock()
    ravi_vp = _unit(2)
    with patch.object(p, "_get_embedding", return_value=np.array(ravi_vp)), \
         patch.object(so, "_speak", speak):
        result = p.process_audio_clip("/tmp/ravi.wav")
    assert result["action"] == "stranger_offer"
    assert so.peek_pending() is not None
    speak.assert_called_once()

    # 3. Room has Jeevan + an unknown -> privacy mode shifts to stranger_present
    ra.record_voice("Jeevan", ts=100.0)
    assert pc.current_mode(now=200.0) == "stranger_present"

    # 4. Jeevan answers "That's Ravi, my brother" -> Ravi gets enrolled
    confirm = so.confirm_stranger("That's Ravi, my brother")
    assert confirm["enrolled"] is True
    p_ravi = reg.get("Ravi")
    assert p_ravi is not None
    assert p_ravi.relation == Relation.FAMILY
    assert p_ravi.voiceprint == ravi_vp

    # 5. Next time the same voice arrives it's recorded under Ravi's name
    with patch.object(p, "_get_embedding", return_value=np.array(ravi_vp)):
        again = p.process_audio_clip("/tmp/ravi2.wav")
    assert again["action"] == "recorded"
    assert again["name"] == "Ravi"


def test_skip_clears_pending_without_enrolling():
    reg.register(Person(name="Jeevan", relation=Relation.SELF,
                        voiceprint=_unit(1), enrolled_at=1.0))
    speak = MagicMock()
    with patch.object(p, "_get_embedding", return_value=np.array(_unit(77))), \
         patch.object(so, "_speak", speak):
        p.process_audio_clip("/tmp/x.wav")
    out = so.confirm_stranger("skip it")
    assert out["enrolled"] is False
    assert so.peek_pending() is None
    assert {pp.name for pp in reg.list_all()} == {"Jeevan"}
