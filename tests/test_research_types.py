"""Tests for Phase 2a shared dataclasses."""
from research_types import (
    SourceTier,
    CitedFact,
    ResearchReport,
    DeliveryEnvelope,
)


def test_source_tier_ordering():
    # tier .weight is the numeric trust score; .value is the string label
    assert SourceTier.JOURNALISM.weight > SourceTier.WIKIPEDIA.weight
    assert SourceTier.WIKIPEDIA.weight > SourceTier.BLOG.weight
    assert SourceTier.ACADEMIC.weight > SourceTier.JOURNALISM.weight
    assert SourceTier.ACADEMIC.value == "academic"


def test_cited_fact_construction():
    f = CitedFact(
        text="Wheat leaf rust is caused by Puccinia triticina",
        source_urls=["https://en.wikipedia.org/wiki/Wheat_leaf_rust"],
        tiers=[SourceTier.WIKIPEDIA],
        confidence=0.7,
    )
    assert f.confidence == 0.7
    assert len(f.source_urls) == 1
    d = f.to_dict()
    assert d["text"].startswith("Wheat")
    assert d["tiers"] == ["wikipedia"]


def test_research_report_construction():
    fact = CitedFact(text="x", source_urls=["u"], tiers=[SourceTier.JOURNALISM], confidence=0.9)
    report = ResearchReport(
        query="wheat rust",
        spoken_brief="Wheat leaf rust is a fungal disease.",
        card_bullets=["caused by Puccinia triticina", "spreads via wind"],
        facts=[fact],
        sources=[{"n": 1, "url": "u", "title": "t"}],
        contradictions=[],
        ms=1234,
    )
    assert report.query == "wheat rust"
    assert len(report.facts) == 1
    d = report.to_dict()
    assert d["query"] == "wheat rust"


def test_delivery_envelope_carries_report_plus_routing():
    fact = CitedFact(text="x", source_urls=["u"], tiers=[SourceTier.JOURNALISM], confidence=0.9)
    report = ResearchReport(
        query="q", spoken_brief="b", card_bullets=["a"], facts=[fact],
        sources=[], contradictions=[], ms=0,
    )
    env = DeliveryEnvelope(report=report, route_voice=True, route_card=True)
    assert env.route_voice is True
    assert env.report.query == "q"
