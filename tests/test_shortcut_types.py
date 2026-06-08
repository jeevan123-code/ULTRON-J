"""Tests for shortcut_types."""
from shortcut_types import Shortcut


def test_shortcut_construction():
    s = Shortcut(
        term="the wheat thing",
        canonical="wheat-3d-explorer",
        confidence=1.0,
        created_at=1700000000.0,
        taught_explicitly=True,
    )
    assert s.term == "the wheat thing"
    assert s.canonical == "wheat-3d-explorer"
    assert s.confidence == 1.0
    assert s.taught_explicitly is True


def test_shortcut_to_dict():
    s = Shortcut(
        term="the wheat thing",
        canonical="wheat-3d-explorer",
        confidence=0.85,
        created_at=1700000000.0,
        taught_explicitly=False,
    )
    d = s.to_dict()
    assert d == {
        "term": "the wheat thing",
        "canonical": "wheat-3d-explorer",
        "confidence": 0.85,
        "created_at": 1700000000.0,
        "taught_explicitly": False,
    }


def test_shortcut_from_dict_roundtrip():
    s = Shortcut(
        term="t", canonical="c", confidence=1.0,
        created_at=42.0, taught_explicitly=True,
    )
    s2 = Shortcut.from_dict(s.to_dict())
    assert s2 == s


def test_shortcut_normalised_term_is_lowercase_trimmed():
    s = Shortcut(
        term="  The Wheat Thing  ",
        canonical="wheat-3d-explorer",
        confidence=1.0,
        created_at=0.0,
        taught_explicitly=True,
    )
    assert s.normalised_term() == "the wheat thing"
