"""Tests for briefing_builder — compose briefing text from data sources."""
from unittest.mock import patch

import pytest

import briefing_builder as bb
from world_event_types import WorldEvent


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    # Default: empty world feed, empty research queue
    monkeypatch.setattr(bb, "_worldfeed_recent", lambda **kw: [])
    monkeypatch.setattr(bb, "_research_queue_snapshot", lambda: [])
    monkeypatch.setattr(bb, "_recent_goals", lambda: [])
    yield


def _ev(title, score=0.5):
    return WorldEvent(title=title, summary="", url="", source="rss", ts=1.0, score=score)


def test_empty_inputs_produces_minimal_briefing():
    out = bb.compose(now=100.0)
    assert isinstance(out, str)
    assert len(out) > 0
    # Should mention the date or "briefing"
    assert "briefing" in out.lower() or "good" in out.lower()


def test_includes_world_section_when_events_present(monkeypatch):
    monkeypatch.setattr(bb, "_worldfeed_recent",
                        lambda **kw: [_ev("AAPL up 3%", 0.9), _ev("MSFT up", 0.7)])
    out = bb.compose(now=100.0, include_worldfeed=True)
    assert "AAPL up 3%" in out
    assert "MSFT up" in out


def test_skips_world_section_when_include_false(monkeypatch):
    monkeypatch.setattr(bb, "_worldfeed_recent",
                        lambda **kw: [_ev("AAPL up 3%", 0.9)])
    out = bb.compose(now=100.0, include_worldfeed=False)
    assert "AAPL up 3%" not in out


def test_includes_research_queue_summary(monkeypatch):
    monkeypatch.setattr(bb, "_research_queue_snapshot", lambda: [
        {"id": "1", "topic": "GraphQL adoption trends", "priority": 4, "ts": 1.0},
        {"id": "2", "topic": "Llama 3 fine-tuning", "priority": 3, "ts": 2.0},
    ])
    out = bb.compose(now=100.0)
    assert "GraphQL" in out or "Llama" in out


def test_includes_recent_goals(monkeypatch):
    monkeypatch.setattr(bb, "_recent_goals", lambda: ["ship phase6", "fix wheat shader"])
    out = bb.compose(now=100.0)
    assert "phase6" in out or "wheat" in out


def test_max_chars_truncates_output(monkeypatch):
    # Many high-scored events
    monkeypatch.setattr(bb, "_worldfeed_recent",
                        lambda **kw: [_ev(f"event {i}", 0.9) for i in range(50)])
    out = bb.compose(now=100.0, max_chars=300)
    assert len(out) <= 300 + 20  # small slack for the "...truncated" marker
