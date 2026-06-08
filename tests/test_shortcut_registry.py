"""Tests for shortcut_registry — JSON-backed CRUD."""
import os
import json
import time
import pytest

import shortcut_registry as reg
from shortcut_types import Shortcut


@pytest.fixture(autouse=True)
def _tmp_file(tmp_path, monkeypatch):
    """Redirect persistence to a tmp file per test."""
    path = tmp_path / "shortcuts.json"
    monkeypatch.setattr(reg, "_REGISTRY_PATH", str(path))
    reg._reset_for_test()
    yield
    reg._reset_for_test()


def _shortcut(term: str, canonical: str = "x") -> Shortcut:
    return Shortcut(
        term=term, canonical=canonical, confidence=1.0,
        created_at=100.0, taught_explicitly=True,
    )


def test_teach_creates_persistent_file():
    reg.teach(_shortcut("the wheat thing", "wheat-3d-explorer"))
    assert os.path.exists(reg._REGISTRY_PATH)
    with open(reg._REGISTRY_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert data[0]["term"] == "the wheat thing"


def test_get_by_term_returns_shortcut():
    reg.teach(_shortcut("the wheat thing", "wheat-3d-explorer"))
    out = reg.get("the wheat thing")
    assert out is not None
    assert out.canonical == "wheat-3d-explorer"


def test_get_is_case_and_whitespace_insensitive():
    reg.teach(_shortcut("The Wheat Thing", "wheat-3d-explorer"))
    assert reg.get("the wheat thing") is not None
    assert reg.get("  THE wheat THING  ") is not None


def test_get_unknown_returns_none():
    assert reg.get("nope") is None


def test_list_all_returns_every_taught_shortcut():
    reg.teach(_shortcut("a", "alpha"))
    reg.teach(_shortcut("b", "beta"))
    everything = reg.list_all()
    terms = sorted(s.term for s in everything)
    assert terms == ["a", "b"]


def test_teach_overwrites_same_term():
    reg.teach(_shortcut("term", "first"))
    reg.teach(_shortcut("term", "second"))
    out = reg.get("term")
    assert out is not None
    assert out.canonical == "second"
    assert len(reg.list_all()) == 1


def test_forget_removes_entry():
    reg.teach(_shortcut("term", "v"))
    assert reg.forget("term") is True
    assert reg.get("term") is None
    assert reg.forget("term") is False


def test_iter_terms_yields_normalised_terms():
    reg.teach(_shortcut("The Wheat Thing", "wheat-3d-explorer"))
    reg.teach(_shortcut(" pepper ", "Pepper Potts"))
    out = sorted(reg.iter_terms())
    assert out == ["pepper", "the wheat thing"]


def test_persistence_roundtrip():
    reg.teach(_shortcut("term", "value"))
    reg._reset_in_memory_for_test()
    reg._load_from_disk()
    assert reg.get("term") is not None


def test_teach_rejects_empty_term():
    with pytest.raises(ValueError):
        reg.teach(_shortcut("", "x"))


def test_teach_rejects_empty_canonical():
    with pytest.raises(ValueError):
        reg.teach(_shortcut("term", ""))
