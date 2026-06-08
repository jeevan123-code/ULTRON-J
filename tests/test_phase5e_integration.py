"""End-to-end Phase 5e: teach utterance -> registry -> resolve in later text."""
import pytest

import shortcut_registry as reg
import shortcut_inferrer as inf
from shortcut_types import Shortcut


@pytest.fixture(autouse=True)
def _tmp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_REGISTRY_PATH", str(tmp_path / "shortcuts.json"))
    reg._reset_for_test()
    yield
    reg._reset_for_test()


def test_full_teach_then_resolve_flow():
    teach = "by 'the wheat thing' I mean wheat-3d-explorer"
    parsed = inf.parse_teach_utterance(teach)
    assert parsed == ("the wheat thing", "wheat-3d-explorer")

    term, canonical = parsed
    reg.teach(Shortcut(
        term=term, canonical=canonical, confidence=1.0,
        created_at=100.0, taught_explicitly=True,
    ))

    out = inf.resolve_in_text("hey ULTRON look up the wheat thing for me")
    assert out == {"the wheat thing": "wheat-3d-explorer"}


def test_teaching_two_shortcuts_then_resolving_both():
    a = inf.parse_teach_utterance("by 'pepper' I mean Pepper-Potts")
    b = inf.parse_teach_utterance("by 'the wheat thing' I mean wheat-3d-explorer")
    assert a == ("pepper", "Pepper-Potts")
    assert b == ("the wheat thing", "wheat-3d-explorer")

    for term, canon in (a, b):
        reg.teach(Shortcut(
            term=term, canonical=canon, confidence=1.0,
            created_at=100.0, taught_explicitly=True,
        ))

    out = inf.resolve_in_text("show pepper the wheat thing tomorrow")
    assert out == {
        "pepper": "Pepper-Potts",
        "the wheat thing": "wheat-3d-explorer",
    }


def test_unrelated_chat_does_not_resolve_or_teach():
    assert inf.parse_teach_utterance("what's the weather today") is None
    reg.teach(Shortcut(
        term="seedling", canonical="wheat-3d-explorer-seedling",
        confidence=1.0, created_at=100.0, taught_explicitly=True,
    ))
    out = inf.resolve_in_text("research quantum computing")
    assert out == {}


def test_re_teaching_overwrites_previous_mapping():
    """User teaches X -> A, then re-teaches X -> B; later resolutions return B."""
    t1 = inf.parse_teach_utterance("by 'wt' I mean wheat-3d-explorer")
    t2 = inf.parse_teach_utterance("by 'wt' I mean wheat-3d-explorer-v2")
    assert t1 is not None and t2 is not None
    for term, canon in (t1, t2):
        reg.teach(Shortcut(term=term, canonical=canon, confidence=1.0,
                           created_at=100.0, taught_explicitly=True))
    out = inf.resolve_in_text("update wt now")
    assert out == {"wt": "wheat-3d-explorer-v2"}
