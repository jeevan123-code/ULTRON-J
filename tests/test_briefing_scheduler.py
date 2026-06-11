"""Tests for briefing_scheduler — CRUD + cron tick dispatch."""
import json
import os
from unittest.mock import MagicMock

import pytest

import briefing_scheduler as bs
from briefing_types import BriefingSchedule


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "_PATH", str(tmp_path / "scheduled_briefings.json"))
    bs._reset_for_test()
    yield
    bs._reset_for_test()


def test_add_persists_to_disk():
    bs.add("morning", "0 8 * * *", channels=["telegram"])
    assert os.path.exists(bs._PATH)
    with open(bs._PATH) as f:
        data = json.load(f)
    assert data[0]["id"] == "morning"


def test_list_all_returns_added_schedules():
    bs.add("a", "0 8 * * *")
    bs.add("b", "0 21 * * *")
    out = bs.list_all()
    ids = sorted(s.id for s in out)
    assert ids == ["a", "b"]


def test_add_replaces_same_id():
    bs.add("morning", "0 8 * * *", channels=["telegram"])
    bs.add("morning", "0 9 * * *", channels=["voice"])
    out = bs.list_all()
    assert len(out) == 1
    assert out[0].cron_expr == "0 9 * * *"
    assert out[0].channels == ["voice"]


def test_remove_deletes_schedule():
    bs.add("x", "0 8 * * *")
    assert bs.remove("x") is True
    assert bs.list_all() == []
    assert bs.remove("x") is False


def test_persistence_roundtrip():
    bs.add("a", "0 8 * * *")
    bs._reset_in_memory_for_test()
    bs._load_from_disk()
    assert any(s.id == "a" for s in bs.list_all())


def test_invalid_cron_expr_raises():
    with pytest.raises(ValueError):
        bs.add("bad", "not a cron expression")


def test_due_returns_schedules_whose_window_includes_now(monkeypatch):
    # 8am daily — should be due at exactly 8:00:00
    bs.add("morning", "0 8 * * *")
    # Pin now to 2026-06-11 08:00:30 — within the 60s window after 08:00
    import datetime as dt
    target = dt.datetime(2026, 6, 11, 8, 0, 30, tzinfo=dt.timezone.utc)
    ts = target.timestamp()
    out = bs.due(now=ts, window_seconds=60.0)
    assert len(out) == 1
    assert out[0].id == "morning"


def test_due_excludes_schedules_outside_window():
    bs.add("morning", "0 8 * * *")
    import datetime as dt
    # 12:00 is far from 08:00 cron
    target = dt.datetime(2026, 6, 11, 12, 0, 0, tzinfo=dt.timezone.utc)
    out = bs.due(now=target.timestamp(), window_seconds=60.0)
    assert out == []


def test_tick_dispatches_due_briefings(monkeypatch):
    bs.add("morning", "0 8 * * *", channels=["telegram"])
    fake_compose = MagicMock(return_value="briefing text")
    fake_deliver = MagicMock(return_value={"telegram": {"ok": True}})
    monkeypatch.setattr(bs, "_compose_briefing", fake_compose)
    monkeypatch.setattr(bs, "_deliver_briefing", fake_deliver)
    import datetime as dt
    ts = dt.datetime(2026, 6, 11, 8, 0, 30, tzinfo=dt.timezone.utc).timestamp()
    results = bs.tick(now=ts, window_seconds=60.0)
    fake_compose.assert_called_once()
    fake_deliver.assert_called_once()
    assert "morning" in results
