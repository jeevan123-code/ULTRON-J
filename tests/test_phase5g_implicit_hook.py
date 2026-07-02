"""Tests for phase5g_implicit_hook — wires implicit_learner into the registry.

Each test points shortcut_registry at a tmp file so the user's real learned
shortcuts (shortcuts/shortcuts.json) are never touched.
"""
import time

import pytest

import shortcut_registry
from shortcut_types import Shortcut
import phase5g_implicit_hook as hook


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    reg = tmp_path / "shortcuts.json"
    monkeypatch.setattr(shortcut_registry, "_REGISTRY_PATH", str(reg))
    monkeypatch.setattr(shortcut_registry, "_cache", [])
    monkeypatch.setattr(shortcut_registry, "_loaded", True)
    hook._reset_for_test()
    yield
    hook._reset_for_test()


def _feed(n, text):
    for _ in range(n):
        hook.observe(text)


def test_tick_registers_high_confidence_proposal():
    # "the wheat thing" co-occurs with "wheat-3d-explorer" across 3 utterances.
    _feed(3, "the wheat thing is wheat-3d-explorer")
    written = hook.tick(min_cooccurrence=3, min_confidence=0.5)
    assert any(s.term == "the wheat thing" and s.canonical == "wheat-3d-explorer"
               for s in written)
    stored = shortcut_registry.get("the wheat thing")
    assert stored is not None
    assert stored.taught_explicitly is False


def test_tick_below_threshold_registers_nothing():
    _feed(2, "run the wheat thing aka wheat-3d-explorer")   # only 2 < min 3
    written = hook.tick(min_cooccurrence=3, min_confidence=0.5)
    assert written == []
    assert shortcut_registry.get("the wheat thing") is None


def test_tick_never_overwrites_explicit_shortcut():
    # User explicitly taught this term -> inferred proposal must not clobber it.
    shortcut_registry.teach(Shortcut(
        term="the wheat thing", canonical="wheat-real-canonical",
        confidence=1.0, created_at=time.time(), taught_explicitly=True,
    ))
    _feed(5, "the wheat thing is wheat-3d-explorer")
    written = hook.tick(min_cooccurrence=3, min_confidence=0.5)
    assert written == []
    stored = shortcut_registry.get("the wheat thing")
    assert stored.taught_explicitly is True
    assert stored.canonical == "wheat-real-canonical"


def test_observe_ignores_empty_and_tick_on_empty_buffer():
    hook.observe("")
    hook.observe("   ")
    assert hook.tick() == []
