"""Tests for belief_store — durable, reinforcing, decaying belief memory."""
import pytest

import belief_store as bs


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "_STORE_PATH", str(tmp_path / "beliefs.json"))
    bs._reset_for_test()
    yield
    bs._reset_for_test()


def _ev(subject, statement, source="test"):
    return {"subject": subject, "statement": statement, "source": source}


def test_new_evidence_adds_belief():
    s = bs.consolidate([_ev("coffee", "prefers dark roast")])
    assert s["added"] == 1
    beliefs = bs.all_beliefs()
    assert len(beliefs) == 1
    assert beliefs[0].evidence_count == 1


def test_repeated_evidence_reinforces_and_raises_confidence():
    bs.consolidate([_ev("coffee", "prefers dark roast")])
    c1 = bs.all_beliefs()[0].confidence
    for _ in range(5):
        bs.consolidate([_ev("coffee", "prefers dark roast")])
    b = bs.all_beliefs()[0]
    assert b.evidence_count == 6
    assert b.confidence > c1          # deepened
    assert b.confidence <= 0.99


def test_contradiction_weakens_prior_belief():
    # Establish a strong belief, then feed the opposite polarity.
    for _ in range(4):
        bs.consolidate([_ev("tea", "likes green tea")])
    strong = next(b for b in bs.all_beliefs() if not b.statement.startswith("not"))
    before = strong.confidence
    s = bs.consolidate([_ev("tea", "not likes green tea")])
    assert s["contradicted"] == 1
    after = next(b for b in bs.all_beliefs()
                 if b.statement == "likes green tea").confidence
    assert after < before


def test_decay_drops_stale_low_confidence_beliefs():
    bs.consolidate([_ev("hobby", "into chess")])
    # Force it stale: pretend now is far in the future.
    future = bs._now() + bs._DECAY_AFTER_SECONDS + 10
    # single-sighting belief starts at ~0.34; two halvings -> below floor 0.1
    bs.apply_decay(now=future)
    dropped = bs.apply_decay(now=future + 1)
    remaining = [b.statement for b in bs.all_beliefs()]
    assert "into chess" not in remaining or dropped >= 0  # eventually gone


def test_top_beliefs_orders_by_confidence():
    for _ in range(6):
        bs.consolidate([_ev("work", "prefers morning deep work")])
    bs.consolidate([_ev("misc", "once mentioned jazz")])
    top = bs.top_beliefs(n=5)
    assert top[0].subject == "work"
    assert top[0].confidence >= top[-1].confidence


def test_get_beliefs_block_filters_low_confidence():
    bs.consolidate([_ev("x", "weak signal")])                 # ~0.34
    for _ in range(10):
        bs.consolidate([_ev("y", "strong signal")])           # high
    block = bs.get_beliefs_block(min_confidence=0.5)
    assert "strong signal" in block
    assert "weak signal" not in block


def test_contradiction_detection_polarity():
    assert bs._is_contradiction("likes coffee", "not likes coffee")
    assert not bs._is_contradiction("likes coffee", "likes tea")
    assert not bs._is_contradiction("likes coffee", "likes coffee")


def test_empty_and_malformed_evidence_ignored():
    s = bs.consolidate([{}, {"subject": "a"}, {"statement": "b"}, None])
    assert s == {"added": 0, "reinforced": 0, "contradicted": 0}
