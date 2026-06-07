"""Tests for person_registry — JSON-backed multi-person CRUD."""
import os
import json
import pytest

import person_registry as reg
from person_types import Person, Relation


@pytest.fixture(autouse=True)
def _tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    yield


def _voiceprint(value: float, length: int = 8) -> list:
    return [value] * length


def test_register_creates_json_file():
    p = Person(name="Ravi", relation=Relation.FAMILY,
               voiceprint=_voiceprint(0.1), enrolled_at=100.0, notes="brother")
    saved = reg.register(p)
    assert saved.name == "Ravi"
    path = os.path.join(reg._PERSONS_DIR, "ravi.json")
    assert os.path.exists(path)
    with open(path) as f:
        data = json.load(f)
    assert data["relation"] == "family"
    assert data["voiceprint"] == _voiceprint(0.1)


def test_get_returns_registered_person():
    p = Person(name="Ravi", relation=Relation.FAMILY,
               voiceprint=_voiceprint(0.1), enrolled_at=100.0)
    reg.register(p)
    out = reg.get("Ravi")
    assert out is not None
    assert out.name == "Ravi"
    assert out.relation == Relation.FAMILY


def test_get_is_case_and_whitespace_insensitive():
    p = Person(name="Ravi Kumar", relation=Relation.FAMILY,
               voiceprint=_voiceprint(0.1), enrolled_at=100.0)
    reg.register(p)
    assert reg.get("ravi kumar") is not None
    assert reg.get("  Ravi  Kumar  ") is not None


def test_get_unknown_returns_none():
    assert reg.get("Nobody") is None


def test_list_all_returns_all_registered():
    reg.register(Person(name="A", relation=Relation.FRIEND,
                        voiceprint=_voiceprint(0.1), enrolled_at=1.0))
    reg.register(Person(name="B", relation=Relation.FAMILY,
                        voiceprint=_voiceprint(0.2), enrolled_at=2.0))
    everyone = reg.list_all()
    names = sorted(p.name for p in everyone)
    assert names == ["A", "B"]


def test_delete_removes_file():
    p = Person(name="Ravi", relation=Relation.FAMILY,
               voiceprint=_voiceprint(0.1), enrolled_at=100.0)
    reg.register(p)
    assert reg.delete("Ravi") is True
    assert reg.get("Ravi") is None
    assert reg.delete("Ravi") is False


def test_iter_voiceprints_yields_name_and_array():
    reg.register(Person(name="Ravi", relation=Relation.FAMILY,
                        voiceprint=_voiceprint(0.1), enrolled_at=1.0))
    reg.register(Person(name="Pepper", relation=Relation.FRIEND,
                        voiceprint=_voiceprint(0.2), enrolled_at=2.0))
    out = sorted(reg.iter_voiceprints(), key=lambda t: t[0])
    assert [name for name, _ in out] == ["Pepper", "Ravi"]
    assert all(len(vp) == 8 for _, vp in out)


def test_register_overwrites_same_slug():
    p1 = Person(name="Ravi", relation=Relation.FAMILY,
                voiceprint=_voiceprint(0.1), enrolled_at=1.0, notes="brother")
    p2 = Person(name="Ravi", relation=Relation.FAMILY,
                voiceprint=_voiceprint(0.9), enrolled_at=2.0, notes="updated")
    reg.register(p1)
    reg.register(p2)
    out = reg.get("Ravi")
    assert out is not None
    assert out.notes == "updated"
    assert out.voiceprint == _voiceprint(0.9)
    files = [f for f in os.listdir(reg._PERSONS_DIR) if f.endswith(".json")]
    assert files == ["ravi.json"]


def test_register_rejects_empty_name():
    p = Person(name="", relation=Relation.FAMILY,
               voiceprint=_voiceprint(0.1), enrolled_at=100.0)
    with pytest.raises(ValueError):
        reg.register(p)
