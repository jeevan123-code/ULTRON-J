"""Tests for world_event_sources — RSS / NewsAPI / Alpha Vantage adapters."""
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest

import world_event_sources as wes


# ---- RSSSource ----

def test_rss_source_fetch_parses_feedparser_entries(monkeypatch):
    fake_feed = SimpleNamespace(entries=[
        SimpleNamespace(
            title="Apple unveils something", link="https://x/a",
            summary="Apple summary", published_parsed=(2026, 1, 1, 12, 0, 0, 0, 0, 0),
        ),
        SimpleNamespace(
            title="Random news", link="https://x/b",
            summary="...", published_parsed=(2026, 1, 2, 12, 0, 0, 0, 0, 0),
        ),
    ])
    monkeypatch.setattr(wes, "_feedparser_parse", lambda url: fake_feed)
    src = wes.RSSSource("https://example.com/feed")
    events = src.fetch()
    assert len(events) == 2
    assert events[0].title == "Apple unveils something"
    assert events[0].source.startswith("rss:")


def test_rss_source_handles_exception(monkeypatch):
    def boom(url): raise RuntimeError("network")
    monkeypatch.setattr(wes, "_feedparser_parse", boom)
    src = wes.RSSSource("https://broken")
    assert src.fetch() == []


def test_rss_source_skips_empty_entries(monkeypatch):
    fake_feed = SimpleNamespace(entries=[
        SimpleNamespace(title="", link="", summary="", published_parsed=None),
    ])
    monkeypatch.setattr(wes, "_feedparser_parse", lambda url: fake_feed)
    src = wes.RSSSource("https://x")
    assert src.fetch() == []


# ---- NewsAPISource ----

def test_newsapi_missing_key_returns_empty():
    src = wes.NewsAPISource(api_key="")
    assert src.fetch() == []


def test_newsapi_success_parses_articles(monkeypatch):
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "status": "ok",
        "articles": [
            {"title": "T1", "description": "D1", "url": "U1", "publishedAt": "2026-01-01T00:00:00Z"},
            {"title": "T2", "description": "D2", "url": "U2", "publishedAt": "2026-01-02T00:00:00Z"},
        ],
    }
    monkeypatch.setattr(wes, "_http_get", lambda url, params=None, headers=None, timeout=10: fake_response)
    src = wes.NewsAPISource(api_key="abc")
    events = src.fetch()
    assert len(events) == 2
    assert events[0].title == "T1"
    assert events[0].source == "newsapi"


def test_newsapi_bad_status_returns_empty(monkeypatch):
    fake_response = MagicMock(status_code=500)
    fake_response.json.return_value = {}
    monkeypatch.setattr(wes, "_http_get", lambda *a, **kw: fake_response)
    src = wes.NewsAPISource(api_key="abc")
    assert src.fetch() == []


# ---- AlphaVantageSource ----

def test_alphavantage_missing_key_returns_empty():
    src = wes.AlphaVantageSource(api_key="", tickers=["AAPL"])
    assert src.fetch() == []


def test_alphavantage_fetches_one_event_per_ticker(monkeypatch):
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "Global Quote": {
            "01. symbol": "AAPL",
            "05. price": "150.00",
            "10. change percent": "2.5%",
        }
    }
    monkeypatch.setattr(wes, "_http_get", lambda *a, **kw: fake_response)
    src = wes.AlphaVantageSource(api_key="xyz", tickers=["AAPL", "MSFT"])
    events = src.fetch()
    assert len(events) == 2
    assert events[0].tickers == ["AAPL"]
    assert "150" in events[0].summary


def test_alphavantage_exception_during_one_ticker_continues_others(monkeypatch):
    call_count = {"n": 0}

    def fake_get(url, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("rate limit")
        r = MagicMock(status_code=200)
        r.json.return_value = {"Global Quote": {
            "01. symbol": "MSFT", "05. price": "300.00", "10. change percent": "1.0%",
        }}
        return r

    monkeypatch.setattr(wes, "_http_get", fake_get)
    src = wes.AlphaVantageSource(api_key="x", tickers=["AAPL", "MSFT"])
    events = src.fetch()
    assert len(events) == 1
    assert events[0].tickers == ["MSFT"]
