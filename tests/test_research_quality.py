"""Source quality for the research pipeline.

Observed live before this change: for "who won the 2022 World Cup final", a
Facebook post yielding 116 characters of text was cited as source [1], ranked
above the Wikipedia article that yielded 8,000. There was no notion of source
authority at all — only a 5-entry junk blocklist — and no minimum on how much
a page had to actually say before it earned a citation.
"""
import research_engine as re_


def _hit(url, title="t"):
    return {"url": url, "title": title, "snippet": "s"}


# ── authority ────────────────────────────────────────────────────────────────
def test_reference_and_official_sources_outrank_unknown_blogs():
    assert re_._authority("https://en.wikipedia.org/wiki/X") > re_._authority("https://some-blog.xyz/p")
    assert re_._authority("https://www.nasa.gov/x") > re_._authority("https://some-blog.xyz/p")
    assert re_._authority("https://mit.edu/x") > re_._authority("https://some-blog.xyz/p")


def test_social_and_ugc_rank_below_unknown_blogs():
    for u in ("https://www.facebook.com/p/1", "https://x.com/a/1",
              "https://www.reddit.com/r/x", "https://medium.com/@a/b"):
        assert re_._authority(u) < re_._authority("https://some-blog.xyz/p"), u


def test_authority_is_case_and_subdomain_insensitive():
    assert re_._authority("https://EN.WIKIPEDIA.ORG/wiki/X") == re_._authority("https://en.wikipedia.org/wiki/X")
    assert re_._authority("https://news.bbc.co.uk/x") > re_._authority("https://some-blog.xyz/p")


def test_unknown_domain_gets_the_neutral_score():
    assert re_._authority("https://totally-unknown-site.example/p") == re_.AUTHORITY_NEUTRAL


# ── _domain: pre-existing bug ────────────────────────────────────────────────
# It used host.lstrip("www."), which strips CHARACTERS in {w, .}, not the
# prefix. So wikipedia.org -> "ikipedia.org", who.int -> "ho.int" and
# washingtonpost.com -> "ashingtonpost.com". The visible casualty was the junk
# blocklist: "wikihow.com" became "ikihow.com" and therefore never matched, so
# one of the five blocked domains was never actually blocked.
def test_domain_strips_the_www_prefix_not_leading_w_characters():
    assert re_._domain("https://wikipedia.org/wiki/X") == "wikipedia.org"
    assert re_._domain("https://who.int/x") == "who.int"
    assert re_._domain("https://washingtonpost.com/x") == "washingtonpost.com"
    assert re_._domain("https://www.bbc.com/news") == "bbc.com"


def test_wikihow_is_actually_blocked_now():
    hits = [_hit("https://www.wikihow.com/Do-Thing"), _hit("https://en.wikipedia.org/wiki/T")]
    out = re_.diversify_sources(hits, max_total=10)
    assert all("wikihow" not in h["url"] for h in out)


def test_domain_is_robust_to_junk_input():
    assert re_._domain("") == ""
    assert re_._domain("not a url") == ""


# ── ordering ─────────────────────────────────────────────────────────────────
def test_diversify_puts_authoritative_sources_first():
    hits = [_hit("https://www.facebook.com/post/1"),
            _hit("https://random-blog.xyz/a"),
            _hit("https://en.wikipedia.org/wiki/Topic")]
    out = re_.diversify_sources(hits, max_total=10)
    assert "wikipedia.org" in out[0]["url"]
    assert "facebook.com" in out[-1]["url"]


def test_ordering_is_stable_within_a_tier():
    hits = [_hit("https://a-blog.xyz/1"), _hit("https://b-blog.xyz/2"),
            _hit("https://c-blog.xyz/3")]
    out = re_.diversify_sources(hits, max_total=10)
    assert [h["url"] for h in out] == [h["url"] for h in hits]


def test_hard_junk_domains_are_still_dropped_entirely():
    hits = [_hit("https://www.pinterest.com/x"), _hit("https://en.wikipedia.org/wiki/T")]
    out = re_.diversify_sources(hits, max_total=10)
    assert all("pinterest" not in h["url"] for h in out)


def test_social_is_demoted_but_not_dropped():
    # Reddit is genuinely the best source for some questions — demote, don't ban.
    hits = [_hit("https://www.reddit.com/r/x"), _hit("https://en.wikipedia.org/wiki/T")]
    out = re_.diversify_sources(hits, max_total=10)
    assert any("reddit" in h["url"] for h in out)


def test_one_result_per_domain_still_holds():
    hits = [_hit("https://en.wikipedia.org/wiki/A"), _hit("https://en.wikipedia.org/wiki/B"),
            _hit("https://other.xyz/a")]
    out = re_.diversify_sources(hits, max_total=2)
    assert len({re_._domain(h["url"]) for h in out}) == 2


# ── thin sources ─────────────────────────────────────────────────────────────
def test_a_page_that_said_almost_nothing_is_not_citable():
    assert re_._is_citable("x" * (re_.MIN_PAGE_CHARS - 1)) is False
    assert re_._is_citable("x" * re_.MIN_PAGE_CHARS) is True


def test_empty_page_is_not_citable():
    assert re_._is_citable("") is False
    assert re_._is_citable(None) is False


def test_min_page_chars_would_have_rejected_the_facebook_source():
    # The real failure: 116 characters became citation [1].
    assert re_._is_citable("x" * 116) is False


# ── cross-referencing ────────────────────────────────────────────────────────
def test_standard_depth_now_cross_references():
    # The fact-checker existed and worked but only ran on "deep", which is not
    # the depth normal questions use.
    assert re_.DEPTH_CONFIG["standard"]["cross_ref"] is True
    assert re_.DEPTH_CONFIG["deep"]["cross_ref"] is True


def test_quick_depth_stays_fast():
    assert re_.DEPTH_CONFIG["quick"]["cross_ref"] is False


# ── thin sources never displace real ones ────────────────────────────────────
def _src(sid, text):
    return {"source_id": sid, "url": f"https://x/{sid}", "title": sid, "text": text}


def test_thin_sources_are_dropped_when_a_real_one_exists():
    kept = re_._prefer_citable([_src("S1", "x" * 116), _src("S2", "y" * 5000)])
    assert [s["source_id"] for s in kept] == ["S2"]


def test_thin_sources_are_kept_when_they_are_all_we_have():
    # Something beats nothing — but only when there is no better option.
    thin = [_src("S1", "x" * 116)]
    assert re_._prefer_citable(thin) == thin


def test_prefer_citable_handles_empty_input():
    assert re_._prefer_citable([]) == []


# ── browser fallback for JS-rendered pages ───────────────────────────────────
def test_rendered_fetch_degrades_to_empty_when_browser_unavailable(monkeypatch):
    monkeypatch.setattr(re_, "_ab_browse",
                        lambda url, js=False: (_ for _ in ()).throw(RuntimeError("no browser")))
    assert re_.fetch_rendered("https://example.com", 1000) == ""


def test_rendered_fetch_asks_for_javascript(monkeypatch):
    seen = {}

    def _fake(url, js=False):
        seen["js"] = js
        return {"success": True, "text": "z" * 900}

    monkeypatch.setattr(re_, "_ab_browse", _fake)
    out = re_.fetch_rendered("https://example.com", 1000)
    assert seen["js"] is True, "the whole point is JS rendering"
    assert len(out) == 900


def test_rendered_fetch_respects_max_chars(monkeypatch):
    monkeypatch.setattr(re_, "_ab_browse",
                        lambda url, js=False: {"success": True, "text": "z" * 9000})
    assert len(re_.fetch_rendered("https://example.com", 1000)) == 1000
