"""Tests for name_relation_parser."""
import pytest

from name_relation_parser import parse_name_relation
from person_types import Relation


@pytest.mark.parametrize("text,name,relation", [
    ("That's Ravi, my brother", "Ravi", Relation.FAMILY),
    ("That is Ravi", "Ravi", Relation.STRANGER),
    ("It's my sister Anna", "Anna", Relation.FAMILY),
    ("This is Pepper, my friend", "Pepper", Relation.FRIEND),
    ("That's my boss Tony", "Tony", Relation.PROFESSIONAL),
    ("his name is Bruce", "Bruce", Relation.STRANGER),
    ("her name is Natasha", "Natasha", Relation.STRANGER),
])
def test_parse_extracts_name_and_relation(text, name, relation):
    out = parse_name_relation(text)
    assert out.name == name
    assert out.relation == relation


@pytest.mark.parametrize("text", [
    "skip it", "not now", "no", "i don't want to", "ignore it",
])
def test_parse_skip_returns_unresolved(text):
    out = parse_name_relation(text)
    assert out.is_resolved is False


@pytest.mark.parametrize("text", [
    "", "what's the weather today", "tell me a joke",
])
def test_parse_unrelated_returns_unresolved(text):
    out = parse_name_relation(text)
    assert out.is_resolved is False


@pytest.mark.parametrize("kin_word,expected", [
    ("brother", Relation.FAMILY),
    ("sister", Relation.FAMILY),
    ("dad", Relation.FAMILY),
    ("mom", Relation.FAMILY),
    ("uncle", Relation.FAMILY),
    ("aunt", Relation.FAMILY),
    ("cousin", Relation.FAMILY),
    ("son", Relation.FAMILY),
    ("daughter", Relation.FAMILY),
    ("friend", Relation.FRIEND),
    ("buddy", Relation.FRIEND),
    ("mate", Relation.FRIEND),
    ("boss", Relation.PROFESSIONAL),
    ("colleague", Relation.PROFESSIONAL),
    ("coworker", Relation.PROFESSIONAL),
    ("client", Relation.PROFESSIONAL),
])
def test_relation_keyword_mapping(kin_word, expected):
    out = parse_name_relation(f"that's John, my {kin_word}")
    assert out.relation == expected
    assert out.name == "John"


def test_capitalises_lowercased_name():
    out = parse_name_relation("that's ravi, my brother")
    assert out.name == "Ravi"
