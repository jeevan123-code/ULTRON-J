"""Tests for privacy_circle.current_mode."""
import pytest

import privacy_circle as pc
import person_registry as reg
import room_awareness as ra
from person_types import Person, Relation


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    ra._reset_for_test()
    yield
    ra._reset_for_test()


def _enroll(name: str, relation: Relation):
    reg.register(Person(name=name, relation=relation,
                        voiceprint=[0.1] * 8, enrolled_at=1.0))


def test_private_when_room_is_empty():
    assert pc.current_mode(now=1000.0) == "private"


def test_private_when_only_self_is_present():
    _enroll("Jeevan", Relation.SELF)
    ra.record_voice("Jeevan", ts=900.0)
    assert pc.current_mode(now=1000.0) == "private"


def test_family_when_self_plus_family():
    _enroll("Jeevan", Relation.SELF)
    _enroll("Ravi", Relation.FAMILY)
    ra.record_voice("Jeevan", ts=900.0)
    ra.record_voice("Ravi", ts=920.0)
    assert pc.current_mode(now=1000.0) == "family"


def test_friends_when_friend_present():
    _enroll("Pepper", Relation.FRIEND)
    ra.record_voice("Pepper", ts=900.0)
    assert pc.current_mode(now=1000.0) == "friends"


def test_professional_when_boss_present():
    _enroll("Tony", Relation.PROFESSIONAL)
    ra.record_voice("Tony", ts=900.0)
    assert pc.current_mode(now=1000.0) == "professional"


def test_professional_overrides_family():
    _enroll("Jeevan", Relation.SELF)
    _enroll("Ravi", Relation.FAMILY)
    _enroll("Tony", Relation.PROFESSIONAL)
    ra.record_voice("Jeevan", ts=900.0)
    ra.record_voice("Ravi", ts=910.0)
    ra.record_voice("Tony", ts=920.0)
    assert pc.current_mode(now=1000.0) == "professional"


def test_stranger_present_overrides_everything():
    _enroll("Tony", Relation.PROFESSIONAL)
    ra.record_voice("Tony", ts=900.0)
    ra.record_voice("_stranger", ts=910.0)
    assert pc.current_mode(now=1000.0) == "stranger_present"


def test_stale_voices_drop_out_of_consideration():
    _enroll("Tony", Relation.PROFESSIONAL)
    ra.record_voice("Tony", ts=100.0)
    assert pc.current_mode(now=1100.0, within_seconds=300) == "private"


def test_unregistered_name_treated_as_stranger():
    ra.record_voice("Mystery", ts=900.0)
    assert pc.current_mode(now=1000.0) == "stranger_present"
