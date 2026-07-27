"""Wikipedia as a real search backend for the research pipeline.

Measured 2026-07-26, every keyless engine we had was refusing us:

    duckduckgo html   HTTP 202, 0 results
    duckduckgo lite   HTTP 202, 0 results
    brave search      CAPTCHA ("Verifying you're not a bot")
    google            blocked
    bing              CAPTCHA ("Please solve the challenge below")
    public searxng    all instances refused

The MediaWiki API answered in 1.1s with 5 results and does not block us. It is
narrower than a web search, but it is the one keyless source that actually
works — and it is high-authority, which is exactly what the ranking work wants.
"""
import local_engine as le


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p


_PAYLOAD = {"query": {"search": [
    {"title": "2022 FIFA World Cup final",
     "snippet": 'Argentina beat <span class="searchmatch">France</span> on penalties'},
    {"title": "Lionel Messi", "snippet": "Argentine footballer"},
]}}


def test_returns_hits_in_the_shared_backend_shape(monkeypatch):
    monkeypatch.setattr(le.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    hits = le.search_wikipedia_hits("world cup final", max_results=5)
    assert len(hits) == 2
    for h in hits:
        assert set(h) >= {"title", "url", "snippet", "source"}
        assert h["source"] == "wikipedia"


def test_builds_real_article_urls(monkeypatch):
    monkeypatch.setattr(le.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    hits = le.search_wikipedia_hits("world cup final")
    assert hits[0]["url"] == "https://en.wikipedia.org/wiki/2022_FIFA_World_Cup_final"


def test_strips_the_html_the_api_puts_in_snippets(monkeypatch):
    monkeypatch.setattr(le.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    snip = le.search_wikipedia_hits("x")[0]["snippet"]
    assert "<span" not in snip and "searchmatch" not in snip
    assert "France" in snip


def test_respects_max_results(monkeypatch):
    monkeypatch.setattr(le.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    assert len(le.search_wikipedia_hits("x", max_results=1)) == 1


def test_network_failure_returns_empty_not_an_exception(monkeypatch):
    def _boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(le.requests, "get", _boom)
    assert le.search_wikipedia_hits("x") == []


def test_bad_status_returns_empty(monkeypatch):
    monkeypatch.setattr(le.requests, "get", lambda *a, **k: _Resp({}, status=429))
    assert le.search_wikipedia_hits("x") == []


def test_malformed_payload_returns_empty(monkeypatch):
    monkeypatch.setattr(le.requests, "get", lambda *a, **k: _Resp({"unexpected": 1}))
    assert le.search_wikipedia_hits("x") == []


# ── registered in the research chain ────────────────────────────────────────
def test_backend_is_registered_and_in_the_default_chain():
    import research_engine as re_
    assert "wikipedia" in re_._BACKENDS
    names = [f.__name__ for f in re_._backend_chain()]
    assert any("wikipedia" in n for n in names), (
        "wikipedia must be in the fallback chain — it is the only keyless "
        "backend that currently returns anything")
