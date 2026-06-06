"""Tests for compound_intent_parser."""
import json
from pathlib import Path
import pytest

from compound_intent_parser import parse, detect_primary
from intent_types import IntentKind, ModifierKind


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


def test_modifier_add():
    result = parse("yes and also add voice activation")
    assert result.primary.kind == IntentKind.AFFIRM
    assert len(result.modifiers) == 1
    m = result.modifiers[0]
    assert m.kind == ModifierKind.ADD
    assert "voice activation" in m.value.lower()


def test_modifier_priority_speed():
    result = parse("go ahead but make it faster")
    assert result.primary.kind == IntentKind.AFFIRM
    assert any(m.kind == ModifierKind.PRIORITY and m.value == "speed" for m in result.modifiers)


def test_modifier_exclude():
    result = parse("sure, but skip the email part")
    assert result.primary.kind == IntentKind.AFFIRM
    assert any(m.kind == ModifierKind.EXCLUDE and "email" in str(m.value).lower() for m in result.modifiers)


def test_modifier_exclude_step():
    result = parse("do everything except step 3")
    assert result.primary.kind == IntentKind.AFFIRM
    assert any(m.kind == ModifierKind.EXCLUDE and "step 3" in str(m.value).lower() for m in result.modifiers)


def test_modifier_switch_to():
    result = parse("nah, do the other one instead")
    assert result.primary.kind == IntentKind.DENY
    assert any(m.kind == ModifierKind.SWITCH_TO for m in result.modifiers)


def test_modifier_pre_check():
    result = parse("yes and check if the wifi is on first")
    assert result.primary.kind == IntentKind.AFFIRM
    assert any(m.kind == ModifierKind.PRE_CHECK and "wifi" in str(m.value).lower() for m in result.modifiers)


def test_two_modifiers_in_one_utterance():
    result = parse("yes and also add voice activation and check if the wifi is on first")
    assert result.primary.kind == IntentKind.AFFIRM
    kinds = {m.kind for m in result.modifiers}
    assert ModifierKind.ADD in kinds
    assert ModifierKind.PRE_CHECK in kinds
