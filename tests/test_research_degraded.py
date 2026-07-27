"""A rate-limited extractor must not silently delete a good source.

Observed live: Groq returned HTTP 429 twice during one research run. The
Guardian's live match report — 3,500 characters, high authority — vanished from
the answer entirely, while a YouTube page that yielded 218 characters survived,
because extract_from_page returns the SAME shape for "the LLM failed" and "this
page is not relevant":

    {"relevant": False, "extract": "", "confidence": "low"}

and the caller then drops everything not marked relevant. So a transient
rate limit quietly narrows the evidence base with no signal to anyone.
"""
import research_engine as re_


PAGE = "Argentina beat France on penalties in the 2022 final. " * 5  # >100 chars


def test_extractor_failure_is_marked_degraded(monkeypatch):
    # LLM produced nothing parseable -> we do NOT know the page is irrelevant.
    monkeypatch.setattr(re_, "ms", None)
    monkeypatch.setattr(re_, "_extract_llm", lambda p, s: "")
    monkeypatch.setattr(re_, "call_llm_batch", lambda p, **kw: "not json at all")
    out = re_.extract_from_page("q", PAGE, "title")
    assert out["degraded"] is True


def test_an_explicit_not_relevant_verdict_is_not_degraded(monkeypatch):
    monkeypatch.setattr(re_, "ms", None)
    monkeypatch.setattr(re_, "_extract_llm",
                        lambda p, s: '{"relevant": false, "extract": "", "confidence": "high"}')
    out = re_.extract_from_page("q", PAGE, "title")
    assert out["relevant"] is False
    assert out.get("degraded") is not True, (
        "the model actually judged this page — that verdict must be respected")


def test_a_successful_extract_is_not_degraded(monkeypatch):
    monkeypatch.setattr(re_, "ms", None)
    monkeypatch.setattr(
        re_, "_extract_llm",
        lambda p, s: '{"relevant": true, "extract": "the fact", "confidence": "high"}')
    out = re_.extract_from_page("q", PAGE, "title")
    assert out["relevant"] is True
    assert out["extract"] == "the fact"
    assert out.get("degraded") is not True


# ── the recovery ─────────────────────────────────────────────────────────────
def test_degraded_source_survives_using_its_own_page_text():
    src = {"source_id": "S1", "url": "https://theguardian.com/x",
           "title": "Match report", "text": "Argentina beat France on penalties. " * 30}
    rec = re_._recover_degraded({"relevant": False, "extract": "", "degraded": True}, src)
    assert rec["relevant"] is True
    assert "Argentina beat France" in rec["extract"]
    assert rec["confidence"] == "low"


def test_recovery_leaves_healthy_extracts_alone():
    src = {"source_id": "S1", "url": "u", "title": "t", "text": "raw page text"}
    good = {"relevant": True, "extract": "the fact", "confidence": "high"}
    assert re_._recover_degraded(good, src) == good


def test_recovery_respects_a_genuine_not_relevant_verdict():
    src = {"source_id": "S1", "url": "u", "title": "t", "text": "raw page text"}
    judged = {"relevant": False, "extract": "", "confidence": "high"}
    assert re_._recover_degraded(judged, src)["relevant"] is False


def test_recovery_cannot_invent_text_from_an_empty_page():
    src = {"source_id": "S1", "url": "u", "title": "t", "text": ""}
    rec = re_._recover_degraded({"relevant": False, "extract": "", "degraded": True}, src)
    assert rec["relevant"] is False


# ── video platforms are not research sources ────────────────────────────────
def test_video_platforms_rank_below_unknown_blogs():
    # A YouTube watch page's scraped "text" is player chrome, not content.
    assert re_._authority("https://www.youtube.com/watch?v=abc") < \
        re_._authority("https://some-blog.xyz/p")


def test_a_page_too_short_to_extract_is_a_real_verdict_not_a_failure():
    # Nothing failed here — the page genuinely had nothing. Must not be
    # "recovered" into the evidence base.
    out = re_.extract_from_page("q", "tiny", "title")
    assert out["relevant"] is False
    assert out.get("degraded") is not True
