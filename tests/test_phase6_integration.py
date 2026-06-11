"""End-to-end Phase 6: poller -> worldfeed -> scheduler tick -> delivery."""
from unittest.mock import MagicMock
import datetime as dt

import pytest

import world_event_poller as wep
import worldfeed_store as wfs
import briefing_scheduler as bs
import briefing_delivery as bd
import interest_matcher as im
from world_event_types import WorldEvent


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(wfs, "_PATH", str(tmp_path / "worldfeed.json"))
    monkeypatch.setattr(bs, "_PATH", str(tmp_path / "scheduled_briefings.json"))
    wfs._reset_for_test()
    bs._reset_for_test()
    wep._reset_for_test()
    yield
    wfs._reset_for_test()
    bs._reset_for_test()
    wep._reset_for_test()


def test_end_to_end_poller_to_telegram_delivery(monkeypatch):
    # 1. Register a source that produces one matched event
    fake_source = MagicMock()
    fake_source.fetch.return_value = [WorldEvent(
        title="AAPL up 3%", summary="apple rallies",
        url="u", source="test", ts=dt.datetime.now(dt.timezone.utc).timestamp(),
    )]
    wep.register("test_source", fake_source)
    monkeypatch.setattr(im, "load_interests", lambda: ["AAPL"])

    # 2. Tick the poller; worldfeed should fill
    wep._tick_for_test("test_source")
    assert len(wfs._snapshot_for_test()) == 1

    # 3. Add a scheduled briefing for 8am UTC
    bs.add("morning", "0 8 * * *", channels=["telegram"], include_worldfeed=True)

    # 4. Stub telegram send so we capture the briefing text
    captured = {}
    monkeypatch.setattr(bd, "_telegram_send",
                        lambda text: captured.setdefault("text", text) or {"ok": True})

    # 5. Tick the scheduler at exactly 8:00:30 UTC
    target_ts = dt.datetime(2026, 6, 11, 8, 0, 30, tzinfo=dt.timezone.utc).timestamp()
    results = bs.tick(now=target_ts, window_seconds=60.0)
    assert "morning" in results
    assert results["morning"]["telegram"]["ok"] is True
    assert "AAPL up 3%" in captured["text"]


def test_end_to_end_one_channel_fails_other_succeeds(monkeypatch):
    # Worldfeed has nothing; briefing only contains greeting (which is fine)
    bs.add("twin_channel", "0 8 * * *", channels=["telegram", "voice"])

    monkeypatch.setattr(bd, "_telegram_send",
                        MagicMock(side_effect=RuntimeError("no token")))
    monkeypatch.setattr(bd, "_voice_say",
                        MagicMock(return_value=(b"audio", "edge")))

    target_ts = dt.datetime(2026, 6, 11, 8, 0, 30, tzinfo=dt.timezone.utc).timestamp()
    results = bs.tick(now=target_ts, window_seconds=60.0)
    assert results["twin_channel"]["telegram"]["ok"] is False
    assert results["twin_channel"]["voice"]["ok"] is True


def test_unscheduled_time_dispatches_nothing(monkeypatch):
    bs.add("morning", "0 8 * * *", channels=["telegram"])
    fake_compose = MagicMock()
    monkeypatch.setattr(bs, "_compose_briefing", fake_compose)
    # Not 8am-ish; cron last fire is much further back than 60s window
    target_ts = dt.datetime(2026, 6, 11, 15, 30, 0, tzinfo=dt.timezone.utc).timestamp()
    results = bs.tick(now=target_ts, window_seconds=60.0)
    assert results == {}
    fake_compose.assert_not_called()
