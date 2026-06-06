"""Tests for research_facts — storing and recalling verified atomic claims."""
from unittest.mock import patch, MagicMock
import research_facts
from research_types import CitedFact, SourceTier, ResearchReport


def _sample_report():
    facts = [
        CitedFact(
            text="Wheat leaf rust is caused by Puccinia triticina",
            source_urls=["https://wikipedia.org/wiki/Wheat_leaf_rust",
                         "https://nature.com/articles/leafrust"],
            tiers=[SourceTier.WIKIPEDIA, SourceTier.ACADEMIC],
            confidence=0.86,
        ),
        CitedFact(
            text="Low confidence claim",
            source_urls=["https://random.example.com/x"],
            tiers=[SourceTier.GENERAL],
            confidence=0.35,
        ),
    ]
    return ResearchReport(
        query="wheat leaf rust", spoken_brief="b", card_bullets=["a"],
        facts=facts, sources=[], contradictions=[], ms=0,
    )


def test_store_only_persists_high_confidence_facts():
    report = _sample_report()
    fake_store = MagicMock()
    with patch.object(research_facts, "_get_vector_store", return_value=fake_store):
        n = research_facts.store_verified_facts(report, min_confidence=0.5)
    assert n == 1
    fake_store.remember.assert_called_once()
    added_text = fake_store.remember.call_args[1]["text"]
    assert "Puccinia" in added_text


def test_store_no_facts_when_all_low_confidence():
    report = _sample_report()
    fake_store = MagicMock()
    with patch.object(research_facts, "_get_vector_store", return_value=fake_store):
        n = research_facts.store_verified_facts(report, min_confidence=0.9)
    assert n == 0
    fake_store.remember.assert_not_called()


def test_recall_returns_top_k_facts():
    fake_store = MagicMock()
    fake_store.recall.return_value = [
        {"text": "fact 1", "score": 0.95, "metadata": {"query": "q1"}},
        {"text": "fact 2", "score": 0.90, "metadata": {"query": "q2"}},
    ]
    with patch.object(research_facts, "_get_vector_store", return_value=fake_store):
        out = research_facts.recall_facts("topic", k=2)
    assert len(out) == 2
    assert out[0]["text"] == "fact 1"


def test_store_handles_vector_store_failure():
    report = _sample_report()
    fake_store = MagicMock()
    fake_store.remember.side_effect = RuntimeError("store down")
    with patch.object(research_facts, "_get_vector_store", return_value=fake_store):
        n = research_facts.store_verified_facts(report, min_confidence=0.5)
    assert n == 0
