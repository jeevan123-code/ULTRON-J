"""Tests for world_event_poller — tick + dispatch + persistence."""
from unittest.mock import MagicMock, patch

import pytest

import world_event_poller as wep
import worldfeed_store as wfs
import interest_matcher as im
from world_event_types import WorldEvent


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(wfs, "_PATH", str(tmp_path / "worldfeed.json"))
    wfs._reset_for_test()
    wep._reset_for_test()
    yield
    wfs._reset_for_test()
    wep._reset_for_test()


def _ev(title="AAPL up", score=0.5):
    return WorldEvent(title=title, summary="", url="", source="test", ts=1.0, score=score)


def test_tick_calls_registered_source_and_writes_matched(monkeypatch):
    fake_source = MagicMock()
    fake_source.fetch.return_value = [_ev("AAPL up 3%")]
    wep.register("alpha", fake_source)
    monkeypatch.setattr(im, "load_interests", lambda: ["AAPL"])
    wep._tick_for_test("alpha")
    fake_source.fetch.assert_called_once()
    recorded = wfs._snapshot_for_test()
    assert len(recorded) == 1
    assert recorded[0].title == "AAPL up 3%"


def test_tick_skips_unknown_source():
    # Should not raise even when name was never registered
    wep._tick_for_test("nope")
    assert wfs._snapshot_for_test() == []


def test_tick_drops_unmatched_events(monkeypatch):
    fake_source = MagicMock()
    fake_source.fetch.return_value = [_ev("Totally unrelated")]
    wep.register("alpha", fake_source)
    monkeypatch.setattr(im, "load_interests", lambda: ["AAPL"])
    wep._tick_for_test("alpha")
    assert wfs._snapshot_for_test() == []


def test_source_exception_does_not_poison_loop(monkeypatch):
    bad = MagicMock()
    bad.fetch.side_effect = RuntimeError("network")
    wep.register("bad", bad)
    monkeypatch.setattr(im, "load_interests", lambda: ["x"])
    # Should not raise
    wep._tick_for_test("bad")
    assert wfs._snapshot_for_test() == []


def test_tick_all_iterates_every_registered(monkeypatch):
    a = MagicMock(); a.fetch.return_value = [_ev("AAPL good")]
    b = MagicMock(); b.fetch.return_value = [_ev("MSFT good")]
    wep.register("alpha", a)
    wep.register("beta", b)
    monkeypatch.setattr(im, "load_interests", lambda: ["AAPL", "MSFT"])
    wep._tick_all_for_test()
    assert a.fetch.call_count == 1
    assert b.fetch.call_count == 1
    titles = {e.title for e in wfs._snapshot_for_test()}
    assert "AAPL good" in titles and "MSFT good" in titles


def test_register_overwrites_same_name(monkeypatch):
    first = MagicMock(); first.fetch.return_value = [_ev("first")]
    second = MagicMock(); second.fetch.return_value = [_ev("second")]
    wep.register("alpha", first)
    wep.register("alpha", second)
    monkeypatch.setattr(im, "load_interests", lambda: ["first", "second"])
    wep._tick_for_test("alpha")
    first.fetch.assert_not_called()
    second.fetch.assert_called_once()
