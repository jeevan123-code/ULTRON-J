"""Tests for action_log — rolling log of ActionEvents with JSON persistence."""
import json
import os
import threading

import pytest

import action_log
from action_types import ActionEvent, ActionKind


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    path = tmp_path / "action_log.json"
    monkeypatch.setattr(action_log, "_PATH", str(path))
    action_log._reset_for_test()
    yield
    action_log._reset_for_test()


def _ev(ts: float, kind: ActionKind = ActionKind.FILE_RENAME, target: str = "x"):
    return ActionEvent(ts=ts, kind=kind, target=target)


def test_recent_starts_empty():
    assert action_log.recent(now=100.0) == []


def test_record_then_recent_returns_event():
    ev = _ev(100.0)
    action_log.record(ev)
    out = action_log.recent(now=200.0, within_seconds=3600)
    assert out == [ev]


def test_recent_filters_by_window():
    action_log.record(_ev(100.0))
    action_log.record(_ev(200.0))
    out = action_log.recent(now=210.0, within_seconds=50)
    assert len(out) == 1
    assert out[0].ts == 200.0


def test_recent_count_filters_by_kind():
    action_log.record(_ev(100.0, ActionKind.FILE_RENAME))
    action_log.record(_ev(101.0, ActionKind.APP_LAUNCH))
    action_log.record(_ev(102.0, ActionKind.FILE_RENAME))
    assert action_log.recent_count(
        now=200.0, within_seconds=3600, kind=ActionKind.FILE_RENAME,
    ) == 2
    assert action_log.recent_count(
        now=200.0, within_seconds=3600, kind=ActionKind.APP_LAUNCH,
    ) == 1


def test_recent_count_no_kind_counts_all():
    action_log.record(_ev(100.0, ActionKind.FILE_RENAME))
    action_log.record(_ev(101.0, ActionKind.APP_LAUNCH))
    assert action_log.recent_count(now=200.0, within_seconds=3600) == 2


def test_buffer_evicts_when_max_exceeded():
    for i in range(action_log.MAX_BUFFER + 25):
        action_log.record(_ev(float(i)))
    snap = action_log._snapshot_for_test()
    assert len(snap) <= action_log.MAX_BUFFER


def test_persistence_writes_to_disk_on_record():
    action_log.record(_ev(100.0, ActionKind.FILE_RENAME, "notes.txt"))
    assert os.path.exists(action_log._PATH)
    with open(action_log._PATH) as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert data[0]["target"] == "notes.txt"


def test_persistence_roundtrip_via_load():
    action_log.record(_ev(100.0, ActionKind.APP_LAUNCH, "zoom"))
    action_log._reset_in_memory_for_test()
    action_log._load_from_disk()
    out = action_log.recent(now=200.0, within_seconds=3600)
    assert len(out) == 1
    assert out[0].target == "zoom"


def test_concurrent_records_are_thread_safe():
    def writer(start):
        for i in range(20):
            action_log.record(_ev(float(start + i)))

    threads = [threading.Thread(target=writer, args=(k * 100,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = action_log._snapshot_for_test()
    assert len(snap) == 80
