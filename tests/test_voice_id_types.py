"""Tests for voice_id_types."""
from voice_id_types import StrangerEvent, ParsedNameRelation
from person_types import Relation


def test_stranger_event_construction():
    ev = StrangerEvent(
        embedding=[0.1, 0.2, 0.3],
        audio_path="/tmp/audio.wav",
        detected_at=1700000000.0,
    )
    assert len(ev.embedding) == 3
    assert ev.audio_path == "/tmp/audio.wav"
    d = ev.to_dict()
    assert d["audio_path"] == "/tmp/audio.wav"
    assert d["embedding"] == [0.1, 0.2, 0.3]


def test_parsed_name_relation_construction():
    p = ParsedNameRelation(name="Ravi", relation=Relation.FAMILY)
    assert p.name == "Ravi"
    assert p.relation == Relation.FAMILY
    assert p.is_resolved is True


def test_parsed_name_relation_unresolved():
    p = ParsedNameRelation(name=None, relation=Relation.STRANGER)
    assert p.is_resolved is False


def test_parsed_name_relation_to_dict():
    p = ParsedNameRelation(name="Ravi", relation=Relation.FAMILY)
    assert p.to_dict() == {"name": "Ravi", "relation": "family", "resolved": True}
