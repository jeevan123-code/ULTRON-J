"""Tests for room_awareness — recent voice tracking."""
import pytest
import room_awareness as ra


@pytest.fixture(autouse=True)
def _reset():
    ra._reset_for_test()
    yield
    ra._reset_for_test()


def test_record_voice_adds_entry():
    ra.record_voice("Ravi", ts=100.0)
    assert ra.last_seen("Ravi") == 100.0


def test_record_voice_with_default_ts_uses_now(monkeypatch):
    monkeypatch.setattr(ra, "_now", lambda: 5000.0)
    ra.record_voice("Ravi")
    assert ra.last_seen("Ravi") == 5000.0


def test_who_is_in_the_room_returns_distinct_recent_names():
    ra.record_voice("Ravi", ts=100.0)
    ra.record_voice("Pepper", ts=120.0)
    ra.record_voice("Ravi", ts=140.0)
    out = ra.who_is_in_the_room(now=200.0, within_seconds=300)
    assert sorted(out) == ["Pepper", "Ravi"]


def test_who_is_in_the_room_filters_stale():
    ra.record_voice("Ravi", ts=100.0)
    ra.record_voice("Pepper", ts=500.0)
    out = ra.who_is_in_the_room(now=600.0, within_seconds=200)
    assert out == ["Pepper"]


def test_who_is_in_the_room_empty_when_silent():
    assert ra.who_is_in_the_room() == []


def test_last_seen_returns_none_when_not_heard():
    assert ra.last_seen("Nobody") is None


def test_buffer_caps_at_max_entries():
    for i in range(ra.MAX_BUFFER + 50):
        ra.record_voice(f"P{i}", ts=float(i))
    snap = ra._snapshot_for_test()
    assert len(snap) <= ra.MAX_BUFFER


def test_record_voice_ignores_empty_name():
    ra.record_voice("", ts=100.0)
    ra.record_voice("   ", ts=100.0)
    assert ra.who_is_in_the_room(now=200.0) == []
