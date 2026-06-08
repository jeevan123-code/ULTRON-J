"""Tests for shortcut_inferrer."""
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


@pytest.mark.parametrize("text,term,canonical", [
    ("by 'the wheat thing' I mean wheat-3d-explorer",
     "the wheat thing", "wheat-3d-explorer"),
    ('by "the wheat thing" I mean wheat-3d-explorer',
     "the wheat thing", "wheat-3d-explorer"),
    ("when I say 'the project', I mean wheat-3d-explorer",
     "the project", "wheat-3d-explorer"),
    ('when I say "the project" I mean wheat-3d-explorer',
     "the project", "wheat-3d-explorer"),
    ("'the project' means wheat-3d-explorer",
     "the project", "wheat-3d-explorer"),
])
def test_parse_teach_utterance_extracts_term_and_canonical(text, term, canonical):
    out = inf.parse_teach_utterance(text)
    assert out is not None
    assert out[0] == term
    assert out[1] == canonical


def test_parse_teach_utterance_uppercase_kept():
    out = inf.parse_teach_utterance("by 'The Wheat Thing' I mean Wheat-3D-Explorer")
    assert out == ("The Wheat Thing", "Wheat-3D-Explorer")


@pytest.mark.parametrize("text", [
    "",
    "what's the weather like",
    "tell me a joke",
    "research wheat leaf rust",
    "by something means nothing",
])
def test_parse_teach_utterance_returns_none_on_unrelated_text(text):
    assert inf.parse_teach_utterance(text) is None


def test_parse_teach_utterance_strips_trailing_punctuation():
    out = inf.parse_teach_utterance("by 'foo' I mean bar-baz.")
    assert out == ("foo", "bar-baz")


def test_parse_teach_utterance_rejects_empty_term():
    """An empty quoted term should not parse."""
    assert inf.parse_teach_utterance("by '' I mean wheat-3d-explorer") is None


def _seed(term: str, canonical: str):
    reg.teach(Shortcut(
        term=term, canonical=canonical, confidence=1.0,
        created_at=100.0, taught_explicitly=True,
    ))


def test_resolve_in_text_finds_known_term():
    _seed("the wheat thing", "wheat-3d-explorer")
    out = inf.resolve_in_text("look up the wheat thing for me")
    assert out == {"the wheat thing": "wheat-3d-explorer"}


def test_resolve_in_text_case_insensitive():
    _seed("The Wheat Thing", "wheat-3d-explorer")
    out = inf.resolve_in_text("LOOK UP THE WHEAT THING please")
    assert out == {"the wheat thing": "wheat-3d-explorer"}


def test_resolve_in_text_multiple_matches():
    _seed("the wheat thing", "wheat-3d-explorer")
    _seed("pepper", "Pepper Potts")
    out = inf.resolve_in_text("show pepper the wheat thing")
    assert out == {
        "the wheat thing": "wheat-3d-explorer",
        "pepper": "Pepper Potts",
    }


def test_resolve_in_text_returns_empty_when_no_match():
    _seed("the wheat thing", "wheat-3d-explorer")
    out = inf.resolve_in_text("research quantum computing")
    assert out == {}


def test_resolve_in_text_respects_word_boundaries():
    """'pep' must NOT match the term 'pepper' as a partial-word substring."""
    _seed("pepper", "Pepper Potts")
    assert inf.resolve_in_text("the pep") == {}


def test_resolve_in_text_empty_input_returns_empty_dict():
    _seed("term", "value")
    assert inf.resolve_in_text("") == {}


def test_resolve_in_text_handles_no_registry_entries():
    assert inf.resolve_in_text("anything") == {}
