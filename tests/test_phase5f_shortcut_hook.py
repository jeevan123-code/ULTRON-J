"""Tests for phase5f_shortcut_hook.apply."""
import pytest

import shortcut_registry as reg
from shortcut_types import Shortcut
from phase5f_shortcut_hook import apply


@pytest.fixture(autouse=True)
def _tmp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", str(tmp_path / "shortcuts.json"))
    reg._reset_for_test()
    yield
    reg._reset_for_test()


def test_apply_persists_teach_utterance():
    """A teach utterance gets persisted to the registry."""
    new_context = apply("by 'the wheat thing' I mean wheat-3d-explorer", context={})
    out = reg.get("the wheat thing")
    assert out is not None
    assert out.canonical == "wheat-3d-explorer"
    assert out.taught_explicitly is True
    assert new_context.get("shortcuts", {}) == {}


def test_apply_resolves_known_shortcut_into_context():
    """Pre-existing shortcuts get resolved and added to context."""
    reg.teach(Shortcut(term="the wheat thing", canonical="wheat-3d-explorer",
                       confidence=1.0, created_at=100.0, taught_explicitly=True))
    new_context = apply("look up the wheat thing for me", context={"foo": "bar"})
    assert new_context["foo"] == "bar"
    assert new_context["shortcuts"] == {"the wheat thing": "wheat-3d-explorer"}


def test_apply_handles_both_teach_and_resolve_in_one_call():
    reg.teach(Shortcut(term="pepper", canonical="Pepper Potts",
                       confidence=1.0, created_at=100.0, taught_explicitly=True))
    new_context = apply(
        "by 'wt' I mean wheat-3d-explorer and pepper is great",
        context={},
    )
    assert reg.get("wt") is not None
    assert new_context["shortcuts"].get("pepper") == "Pepper Potts"


def test_apply_returns_new_dict_not_mutating_input():
    reg.teach(Shortcut(term="x", canonical="y", confidence=1.0,
                       created_at=100.0, taught_explicitly=True))
    original = {"foo": "bar"}
    new_context = apply("hello x", context=original)
    assert "shortcuts" not in original
    assert new_context["shortcuts"] == {"x": "y"}


def test_apply_with_none_context():
    """None context is treated as an empty dict."""
    reg.teach(Shortcut(term="x", canonical="y", confidence=1.0,
                       created_at=100.0, taught_explicitly=True))
    new_context = apply("hello x", context=None)
    assert new_context["shortcuts"] == {"x": "y"}


def test_apply_unrelated_utterance_is_noop():
    new_context = apply("what is the weather today", context={"x": 1})
    assert new_context["x"] == 1
    assert new_context.get("shortcuts", {}) == {}


def test_apply_handles_empty_raw():
    new_context = apply("", context={"y": 2})
    assert new_context["y"] == 2
    assert new_context.get("shortcuts", {}) == {}
