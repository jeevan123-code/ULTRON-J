"""Tests for compound_intent_parser."""
import json
from pathlib import Path
import pytest

from compound_intent_parser import parse, detect_primary
from intent_types import IntentKind


def _load_corpus():
    path = Path(__file__).parent / "fixtures" / "utterances.json"
    return json.loads(path.read_text())


@pytest.mark.parametrize("raw,expected", [
    ("yes", IntentKind.AFFIRM),
    ("go ahead", IntentKind.AFFIRM),
    ("sure", IntentKind.AFFIRM),
    ("yep", IntentKind.AFFIRM),
    ("do it", IntentKind.AFFIRM),
    ("bet", IntentKind.AFFIRM),
    ("yeah man", IntentKind.AFFIRM),
    ("ok", IntentKind.AFFIRM),
    ("OK", IntentKind.AFFIRM),
    ("Yes please", IntentKind.AFFIRM),
])
def test_detect_primary_affirm(raw, expected):
    assert detect_primary(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("no", IntentKind.DENY),
    ("nah", IntentKind.DENY),
    ("skip it", IntentKind.DENY),
    ("not now", IntentKind.DENY),
    ("forget it", IntentKind.DENY),
    ("nope", IntentKind.DENY),
    ("No thanks", IntentKind.DENY),
])
def test_detect_primary_deny(raw, expected):
    assert detect_primary(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("wait", IntentKind.DEFER),
    ("pause", IntentKind.DEFER),
    ("hmm let me think", IntentKind.DEFER),
])
def test_detect_primary_defer(raw, expected):
    assert detect_primary(raw) == expected


def test_detect_primary_unknown_returns_none():
    assert detect_primary("the weather is nice today") is None


def test_parse_returns_parsed_utterance_for_simple_affirm():
    result = parse("yes")
    assert result.raw == "yes"
    assert result.primary.kind == IntentKind.AFFIRM
    assert result.modifiers == []


@pytest.mark.parametrize("raw,expected", [
    ("yes!", IntentKind.AFFIRM),
    ("yes?", IntentKind.AFFIRM),
    ("yes;", IntentKind.AFFIRM),
    ("yes:", IntentKind.AFFIRM),
    ("no!", IntentKind.DENY),
    ("no?", IntentKind.DENY),
    ("nope!", IntentKind.DENY),
    ("wait!", IntentKind.DEFER),
])
def test_detect_primary_handles_extra_punctuation(raw, expected):
    assert detect_primary(raw) == expected
