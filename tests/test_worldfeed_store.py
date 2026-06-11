"""Tests for worldfeed_store — JSON-backed ranked feed."""
import json
import os
import threading

import pytest

import worldfeed_store as wfs
from world_event_types import WorldEvent


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(wfs, "_PATH", str(tmp_path / "worldfeed.json"))
    wfs._reset_for_test()
    yield
    wfs._reset_for_test()


def _ev(ts=1.0, score=0.5, source="rss", title="t"):
    return WorldEvent(title=title, summary="", url="u", source=source, ts=ts, score=score)


def test_recent_starts_empty():
    assert wfs.recent(now=100.0) == []


def test_record_and_recent():
    e = _ev(ts=10.0)
    wfs.record(e)
    out = wfs.recent(now=20.0, within_seconds=3600)
    assert out == [e]


def test_recent_filters_by_window():
    wfs.record(_ev(ts=10.0))
    wfs.record(_ev(ts=100.0))
    out = wfs.recent(now=110.0, within_seconds=20)
    assert len(out) == 1
    assert out[0].ts == 100.0


def test_recent_top_n_orders_by_score_desc():
    wfs.record(_ev(ts=10.0, score=0.2, title="low"))
    wfs.record(_ev(ts=11.0, score=0.9, title="high"))
    wfs.record(_ev(ts=12.0, score=0.5, title="mid"))
    out = wfs.recent(now=20.0, within_seconds=3600, top_n=2)
    assert len(out) == 2
    assert out[0].title == "high"
    assert out[1].title == "mid"


def test_buffer_evicts_when_max_exceeded():
    for i in range(wfs.MAX_BUFFER + 25):
        wfs.record(_ev(ts=float(i)))
    snap = wfs._snapshot_for_test()
    assert len(snap) <= wfs.MAX_BUFFER


def test_persistence_to_disk():
    wfs.record(_ev(ts=1.0, source="newsapi", title="hello"))
    assert os.path.exists(wfs._PATH)
    with open(wfs._PATH) as f:
        data = json.load(f)
    assert data[0]["title"] == "hello"


def test_persistence_roundtrip():
    wfs.record(_ev(ts=1.0, source="rss", title="alpha"))
    wfs._reset_in_memory_for_test()
    wfs._load_from_disk()
    out = wfs.recent(now=100.0, within_seconds=3600)
    assert len(out) == 1
    assert out[0].title == "alpha"


def test_concurrent_records_are_thread_safe():
    def writer(start):
        for i in range(20):
            wfs.record(_ev(ts=float(start + i)))

    threads = [threading.Thread(target=writer, args=(k * 100,)) for k in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(wfs._snapshot_for_test()) == 80
