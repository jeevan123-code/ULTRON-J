"""Tests for world_event_types — WorldEvent dataclass."""
import pytest

from world_event_types import WorldEvent


def test_construct_world_event():
    e = WorldEvent(
        title="AAPL up 3%", summary="Apple stock rallies on iPhone news",
        url="https://example.com/aapl", source="alphavantage",
        ts=100.0, tickers=["AAPL"], score=0.75,
    )
    assert e.title == "AAPL up 3%"
    assert e.tickers == ["AAPL"]
    assert e.score == 0.75


def test_defaults():
    e = WorldEvent(title="x", summary="", url="", source="rss", ts=1.0)
    assert e.tickers == []
    assert e.score == 0.0


def test_to_dict_roundtrip():
    e = WorldEvent(
        title="t", summary="s", url="u", source="newsapi",
        ts=10.0, tickers=["X"], score=0.5,
    )
    d = e.to_dict()
    assert d["source"] == "newsapi"
    back = WorldEvent.from_dict(d)
    assert back == e


def test_from_dict_missing_optional_fields():
    e = WorldEvent.from_dict({
        "title": "t", "summary": "s", "url": "u",
        "source": "rss", "ts": 1.0,
    })
    assert e.tickers == []
    assert e.score == 0.0


def test_score_is_clamped_to_zero_one():
    e = WorldEvent(title="x", summary="", url="", source="rss", ts=1.0, score=5.0)
    assert e.score == 1.0
    e2 = WorldEvent(title="x", summary="", url="", source="rss", ts=1.0, score=-0.5)
    assert e2.score == 0.0
