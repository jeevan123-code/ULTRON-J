"""Tests for mind_tick — the Phase 7 unifier."""
from unittest.mock import MagicMock
import datetime as dt

import pytest

import mind_tick
import action_log
import worldfeed_store as wfs
import briefing_scheduler as bs
import proactive_offer as po
from action_types import ActionEvent, ActionKind
from world_event_types import WorldEvent


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(action_log, "_PATH", str(tmp_path / "action_log.json"))
    monkeypatch.setattr(wfs, "_PATH", str(tmp_path / "worldfeed.json"))
    monkeypatch.setattr(bs, "_PATH", str(tmp_path / "scheduled_briefings.json"))
    action_log._reset_for_test()
    wfs._reset_for_test()
    bs._reset_for_test()
    po._reset_for_test()
    mind_tick._reset_for_test()
    yield
    mind_tick._reset_for_test()


def test_tick_with_nothing_due_returns_clean_summary():
    out = mind_tick.tick()
    assert isinstance(out, dict)
    assert out["briefings_dispatched"] == 0
    assert out["world_alerts"] == 0
    assert out["improvement_offers"] == 0


def test_tick_dispatches_due_briefing(monkeypatch):
    bs.add("morning", "0 8 * * *", channels=["telegram"])
    fake_deliver = MagicMock(return_value={"telegram": {"ok": True}})
    monkeypatch.setattr(bs, "_deliver_briefing", fake_deliver)
    monkeypatch.setattr(bs, "_compose_briefing", lambda *a, **kw: "morning text")
    target_ts = dt.datetime(2026, 6, 11, 8, 0, 30, tzinfo=dt.timezone.utc).timestamp()
    out = mind_tick.tick(now=target_ts)
    assert out["briefings_dispatched"] == 1
    fake_deliver.assert_called_once()


def test_tick_alerts_high_score_worldfeed(monkeypatch):
    # Two events: one high-score, one low — only the high one alerts
    import time as _t
    now = _t.time()
    wfs.record(WorldEvent(title="AAPL halted", summary="x", url="u",
                          source="av", ts=now - 30, score=0.95))
    wfs.record(WorldEvent(title="boring", summary="x", url="u",
                          source="rss", ts=now - 30, score=0.4))
    fake_alert = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(mind_tick, "_telegram_alert", fake_alert)
    out = mind_tick.tick(now=now)
    assert out["world_alerts"] == 1
    fake_alert.assert_called_once()
    text = fake_alert.call_args[0][0]
    assert "AAPL halted" in text
    assert "boring" not in text


def test_tick_only_alerts_each_event_once(monkeypatch):
    import time as _t
    now = _t.time()
    wfs.record(WorldEvent(title="huge story", summary="", url="u",
                          source="rss", ts=now - 30, score=0.95))
    fake_alert = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(mind_tick, "_telegram_alert", fake_alert)
    mind_tick.tick(now=now)
    mind_tick.tick(now=now)  # second call should NOT re-alert
    assert fake_alert.call_count == 1


def test_tick_parks_improvement_suggestion(monkeypatch):
    import time as _t
    now = _t.time()
    for i in range(6):
        action_log.record(ActionEvent(
            ts=now - 30 + i, kind=ActionKind.FILE_RENAME, target=f"f{i}.md",
        ))
    out = mind_tick.tick(now=now)
    assert out["improvement_offers"] >= 1
    pending = po.peek_pending_offer()
    assert pending is not None
    assert pending.get("kind") == "improvement"


def test_tick_skips_improvement_if_offer_already_pending(monkeypatch):
    import time as _t
    now = _t.time()
    for i in range(6):
        action_log.record(ActionEvent(
            ts=now - 30 + i, kind=ActionKind.FILE_RENAME, target=f"f{i}.md",
        ))
    out1 = mind_tick.tick(now=now)
    assert out1["improvement_offers"] >= 1
    out2 = mind_tick.tick(now=now)
    # Second tick should not park another improvement (offer still pending)
    assert out2["improvement_offers"] == 0


def test_tick_exception_in_one_stage_does_not_abort_others(monkeypatch):
    bs.add("morning", "0 8 * * *", channels=["telegram"])
    monkeypatch.setattr(bs, "tick",
                        MagicMock(side_effect=RuntimeError("scheduler boom")))
    # The world-alert + improvement stages should still run despite scheduler failure
    out = mind_tick.tick(now=dt.datetime(2026, 6, 11, 8, 0, 30,
                                         tzinfo=dt.timezone.utc).timestamp())
    assert out["briefings_dispatched"] == 0
    assert "scheduler_error" in out
