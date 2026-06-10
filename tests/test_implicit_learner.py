"""Tests for implicit_learner — discover shortcuts from utterance co-occurrence."""
import pytest

from implicit_learner import (
    propose_shortcuts,
    extract_slang_candidates,
    extract_canonical_candidates,
    ProposedShortcut,
)


# ─────────────────────────────────────────────────────────────────────────────
# Candidate extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_canonical_finds_hyphenated_tokens():
    out = extract_canonical_candidates("ship the wheat-3d-explorer today")
    assert "wheat-3d-explorer" in out


def test_extract_canonical_ignores_plain_words():
    out = extract_canonical_candidates("just plain words here")
    assert out == set()


def test_extract_canonical_finds_multiple():
    out = extract_canonical_candidates("compare wheat-3d-explorer and rice-3d-explorer")
    assert "wheat-3d-explorer" in out
    assert "rice-3d-explorer" in out


def test_extract_canonical_ignores_single_word():
    """A single-word token like 'wheat' is NOT a canonical candidate."""
    out = extract_canonical_candidates("just say wheat please")
    assert out == set()


def test_extract_slang_finds_the_x_phrases():
    out = extract_slang_candidates("look up the wheat thing for me")
    assert "the wheat thing" in out


def test_extract_slang_finds_that_x_phrases():
    out = extract_slang_candidates("research that wheat project")
    assert "that wheat project" in out


def test_extract_slang_ignores_articles_alone():
    """'the' alone (no noun after) is not a slang phrase."""
    out = extract_slang_candidates("just the")
    assert out == set()


def test_extract_slang_returns_lowercase():
    out = extract_slang_candidates("Look up The Wheat Thing")
    assert "the wheat thing" in out


# ─────────────────────────────────────────────────────────────────────────────
# Co-occurrence proposal
# ─────────────────────────────────────────────────────────────────────────────

def test_propose_shortcuts_returns_empty_for_no_utterances():
    assert propose_shortcuts([]) == []


def test_propose_shortcuts_returns_empty_below_threshold():
    """Single occurrence shouldn't propose anything."""
    out = propose_shortcuts(
        ["check the wheat thing in wheat-3d-explorer"],
        min_cooccurrence=3,
    )
    assert out == []


def test_propose_shortcuts_returns_pair_after_threshold():
    """Three co-occurrences of the same (slang, canonical) → propose it."""
    utts = [
        "check the wheat thing in wheat-3d-explorer",
        "update the wheat thing — wheat-3d-explorer needs fixes",
        "ship the wheat thing today; wheat-3d-explorer is ready",
    ]
    out = propose_shortcuts(utts, min_cooccurrence=3)
    assert len(out) == 1
    p = out[0]
    assert isinstance(p, ProposedShortcut)
    assert p.slang == "the wheat thing"
    assert p.canonical == "wheat-3d-explorer"
    assert p.cooccurrences == 3


def test_propose_shortcuts_ignores_random_noise():
    """If slang and canonical don't co-occur, no proposal."""
    utts = [
        "discuss the wheat thing",
        "discuss the wheat thing",
        "ship wheat-3d-explorer next week",
    ]
    out = propose_shortcuts(utts, min_cooccurrence=2)
    # the wheat thing appears 2x but never with the canonical
    assert out == []


def test_propose_shortcuts_threshold_parameter_works():
    utts = [
        "the wheat thing → wheat-3d-explorer",
        "the wheat thing → wheat-3d-explorer",
    ]
    # Threshold=2: should propose
    assert len(propose_shortcuts(utts, min_cooccurrence=2)) == 1
    # Threshold=3: too few co-occurrences
    assert propose_shortcuts(utts, min_cooccurrence=3) == []


def test_proposed_shortcut_to_dict():
    p = ProposedShortcut(
        slang="the wheat thing",
        canonical="wheat-3d-explorer",
        cooccurrences=4,
        confidence=0.9,
    )
    d = p.to_dict()
    assert d == {
        "slang": "the wheat thing",
        "canonical": "wheat-3d-explorer",
        "cooccurrences": 4,
        "confidence": 0.9,
    }


def test_propose_shortcuts_confidence_increases_with_count():
    """More co-occurrences → higher confidence."""
    a = propose_shortcuts(
        ["the X in X-foo", "the X with X-foo"],
        min_cooccurrence=2,
    )
    b = propose_shortcuts(
        ["the Y in Y-foo"] * 10,
        min_cooccurrence=2,
    )
    assert len(a) == 1 and len(b) == 1
    # 10 cooccurrences should yield higher confidence than 2
    assert b[0].confidence > a[0].confidence
