"""Citations in the answer must map to sources in the list.

Observed live: an answer citing [1, 2, 3] came back with exactly ONE source
attached. The renumbering regex is r"\\[(S?\\d+)\\]", which matches "[1]" but not
the grouped form "[1, 2, 3]" that the synthesiser actually emits most of the
time. Every id inside a group was therefore invisible: not remapped, and never
added to the sources list.

The user-visible effect is the worst kind — an answer that looks MORE sourced
than it is, with [2] and [3] pointing at nothing.
"""
import research_engine as re_


def _ex(sid, url):
    return {"source_id": sid, "url": url, "title": f"title {sid}", "extract": "x"}


EXTRACTS = [_ex("S1", "https://a.example"), _ex("S2", "https://b.example"),
            _ex("S3", "https://c.example")]


def test_single_citations_still_work():
    out = re_._renumber_citations("Fact [S1]. Other [S2].", EXTRACTS)
    assert len(out["sources"]) == 2
    assert out["answer"] == "Fact [1]. Other [2]."


def test_grouped_citations_are_parsed():
    out = re_._renumber_citations("Argentina won [1, 2, 3].", EXTRACTS)
    assert len(out["sources"]) == 3, "every id in a group must map to a source"
    assert [s["url"] for s in out["sources"]] == [
        "https://a.example", "https://b.example", "https://c.example"]


def test_grouped_citations_are_renumbered_in_the_answer():
    out = re_._renumber_citations("Only these [2, 3].", EXTRACTS)
    assert out["answer"] == "Only these [1, 2]."
    assert len(out["sources"]) == 2


def test_grouped_s_prefixed_citations():
    out = re_._renumber_citations("Fact [S2, S3].", EXTRACTS)
    assert len(out["sources"]) == 2
    assert out["sources"][0]["url"] == "https://b.example"


def test_mixed_single_and_grouped():
    out = re_._renumber_citations("A [1]. B [2, 3]. C [1].", EXTRACTS)
    assert len(out["sources"]) == 3
    assert out["answer"] == "A [1]. B [2, 3]. C [1]."


def test_order_of_first_appearance_drives_numbering():
    out = re_._renumber_citations("First [3]. Then [1].", EXTRACTS)
    assert out["answer"] == "First [1]. Then [2]."
    assert out["sources"][0]["url"] == "https://c.example"


def test_citation_to_a_source_that_does_not_exist_is_not_invented():
    out = re_._renumber_citations("Claim [1, 9].", EXTRACTS)
    urls = [s["url"] for s in out["sources"]]
    assert "https://a.example" in urls
    assert len(out["sources"]) == 1, "S9 has no extract — it must not appear"


def test_no_citations_yields_no_sources():
    out = re_._renumber_citations("A plain answer.", EXTRACTS)
    assert out["sources"] == []
    assert out["answer"] == "A plain answer."


def test_whitespace_variants_in_groups():
    for text in ("[1,2]", "[1, 2]", "[1 , 2]"):
        out = re_._renumber_citations(f"X {text}.", EXTRACTS)
        assert len(out["sources"]) == 2, text
