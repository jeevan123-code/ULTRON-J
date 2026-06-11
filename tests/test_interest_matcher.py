"""Tests for interest_matcher — load + score WorldEvents by interest keywords."""
import json
import pytest

import interest_matcher as im
from world_event_types import WorldEvent


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "_PATH", str(tmp_path / "interests.json"))
    yield


def _ev(title="hello world", summary="nothing"):
    return WorldEvent(title=title, summary=summary, url="", source="rss", ts=1.0)


def test_load_explicit_interests(tmp_path, monkeypatch):
    path = tmp_path / "interests.json"
    path.write_text(json.dumps(["AAPL", "agriculture"]))
    monkeypatch.setattr(im, "_PATH", str(path))
    out = im.load_interests()
    assert set(out) >= {"AAPL", "agriculture"}


def test_load_falls_back_to_conversation_listener_when_missing(monkeypatch):
    fake_listener = type("X", (), {
        "snapshot": staticmethod(lambda: [
            {"text": "thinking about wheat plant explorer", "ts": 1.0, "processed": False},
            {"text": "claude code is amazing", "ts": 2.0, "processed": True},
        ]),
    })
    monkeypatch.setattr(im, "_listener_snapshot", lambda: fake_listener.snapshot())
    out = im.load_interests()
    text = " ".join(out).lower()
    assert "wheat" in text or "claude" in text


def test_explicit_overrides_auto(tmp_path, monkeypatch):
    path = tmp_path / "interests.json"
    path.write_text(json.dumps(["NVDA"]))
    monkeypatch.setattr(im, "_PATH", str(path))
    monkeypatch.setattr(im, "_listener_snapshot",
                        lambda: [{"text": "anything", "ts": 1.0, "processed": False}])
    out = im.load_interests()
    # Explicit list present → exact contents are returned (no auto-merge appended).
    assert out == ["NVDA"]


def test_match_returns_only_events_with_score_above_zero():
    events = [
        _ev(title="AAPL up 3%", summary="apple rallies"),
        _ev(title="random news", summary="totally unrelated"),
    ]
    out = im.match(events, ["AAPL"])
    assert len(out) == 1
    assert out[0].title.startswith("AAPL")
    assert out[0].score > 0.0


def test_match_is_case_insensitive():
    events = [_ev(title="aapl drops", summary="")]
    out = im.match(events, ["AAPL"])
    assert len(out) == 1


def test_match_sorts_by_score_desc():
    events = [
        _ev(title="AAPL minor mention", summary="other stuff"),
        _ev(title="AAPL AAPL AAPL", summary="AAPL again"),
        _ev(title="totally unrelated", summary=""),
    ]
    out = im.match(events, ["AAPL"])
    assert len(out) == 2
    assert out[0].title.count("AAPL") >= out[1].title.count("AAPL")


def test_empty_interests_returns_empty():
    events = [_ev(title="AAPL", summary="")]
    assert im.match(events, []) == []
