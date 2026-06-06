"""Tests for converting research_engine output into a ResearchReport."""
from research_types import report_from_research_dict, SourceTier
from tests.fixtures.research_responses import wheat_rust_report, report_with_contradictions


def test_report_from_research_dict_basic():
    d = wheat_rust_report()
    report = report_from_research_dict("wheat leaf rust", d)
    assert report.query == "wheat leaf rust"
    assert report.ms == d["ms"]
    assert len(report.sources) == len(d["sources"])
    assert report.contradictions == d["contradictions"]


def test_report_from_research_dict_extracts_card_bullets_from_sentences():
    d = wheat_rust_report()
    report = report_from_research_dict("wheat leaf rust", d)
    assert 1 <= len(report.card_bullets) <= 12


def test_report_from_research_dict_spoken_brief_is_short():
    d = wheat_rust_report()
    report = report_from_research_dict("wheat leaf rust", d)
    assert "[1]" not in report.spoken_brief
    assert len(report.spoken_brief) < 1500


def test_report_from_research_dict_facts_carry_tiers_from_sources():
    d = wheat_rust_report()
    report = report_from_research_dict("wheat leaf rust", d)
    assert any(SourceTier.WIKIPEDIA in f.tiers for f in report.facts)
    assert any(SourceTier.JOURNALISM in f.tiers for f in report.facts)


def test_report_preserves_contradictions():
    d = report_with_contradictions()
    report = report_from_research_dict("q", d)
    assert len(report.contradictions) == 1
