"""Tests for struggle_counter — rolling log of struggle timestamps."""
import pytest
import struggle_counter as sc


@pytest.fixture(autouse=True)
def _reset():
    sc._reset_for_test()
    yield
    sc._reset_for_test()


def test_recent_count_starts_at_zero():
    assert sc.recent_count(now=100.0) == 0


def test_record_struggle_adds_entry():
    sc.record_struggle(ts=100.0)
    assert sc.recent_count(now=200.0, within_seconds=3600) == 1


def test_recent_count_filters_old_entries():
    sc.record_struggle(ts=100.0)
    sc.record_struggle(ts=200.0)
    assert sc.recent_count(now=210.0, within_seconds=50) == 1


def test_recent_count_includes_entries_on_window_boundary():
    sc.record_struggle(ts=100.0)
    assert sc.recent_count(now=200.0, within_seconds=100) == 1


def test_record_struggle_with_default_ts_uses_now(monkeypatch):
    monkeypatch.setattr(sc, "_now", lambda: 500.0)
    sc.record_struggle()
    assert sc.recent_count(now=510.0, within_seconds=60) == 1


def test_buffer_caps_at_max_entries():
    for i in range(sc.MAX_BUFFER + 50):
        sc.record_struggle(ts=float(i))
    snap = sc._snapshot_for_test()
    assert len(snap) <= sc.MAX_BUFFER


def test_recent_count_default_window_is_one_hour():
    sc.record_struggle(ts=100.0)
    assert sc.recent_count(now=3699.0) == 1
    assert sc.recent_count(now=3701.0) == 0
