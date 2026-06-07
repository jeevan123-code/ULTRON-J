"""Tests for person_types."""
import pytest
from person_types import Person, Relation, RecognitionResult


def test_relation_values():
    assert Relation.SELF.value == "self"
    assert Relation.FAMILY.value == "family"
    assert Relation.FRIEND.value == "friend"
    assert Relation.PROFESSIONAL.value == "professional"
    assert Relation.STRANGER.value == "stranger"


def test_person_construction():
    p = Person(
        name="Ravi",
        relation=Relation.FAMILY,
        voiceprint=[0.1, 0.2, 0.3],
        enrolled_at=1700000000.0,
        notes="brother",
    )
    assert p.name == "Ravi"
    assert p.relation == Relation.FAMILY
    assert len(p.voiceprint) == 3


def test_person_slug():
    assert Person.slug_for("Ravi") == "ravi"
    assert Person.slug_for("Ravi Kumar") == "ravi-kumar"
    assert Person.slug_for("  Ravi   Kumar  ") == "ravi-kumar"
    assert Person.slug_for("Anna-Marie O'Neill") == "anna-marie-oneill"


def test_person_to_dict_and_from_dict():
    p = Person(name="Ravi", relation=Relation.FAMILY,
               voiceprint=[0.1, 0.2], enrolled_at=100.0, notes="b")
    d = p.to_dict()
    assert d["name"] == "Ravi"
    assert d["relation"] == "family"
    assert d["voiceprint"] == [0.1, 0.2]
    p2 = Person.from_dict(d)
    assert p2 == p


def test_recognition_result_construction():
    r = RecognitionResult(name="Ravi", similarity=0.91, threshold=0.75)
    assert r.matched is True
    assert r.name == "Ravi"
    assert r.similarity == 0.91


def test_recognition_result_no_match():
    r = RecognitionResult(name=None, similarity=0.30, threshold=0.75)
    assert r.matched is False
    assert r.name is None


def test_recognition_result_to_dict():
    r = RecognitionResult(name="Ravi", similarity=0.91, threshold=0.75)
    d = r.to_dict()
    assert d == {"name": "Ravi", "similarity": 0.91, "threshold": 0.75, "matched": True}
