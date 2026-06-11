"""Tests for the Phase 6 voice_engine hook."""
from unittest.mock import MagicMock

import pytest

import voice_engine
import worldfeed_store as wfs
from world_event_types import WorldEvent


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(wfs, "_PATH", str(tmp_path / "worldfeed.json"))
    wfs._reset_for_test()
    for flag in ("ULTRON_PHASE1_ENABLED", "ULTRON_PHASE2A_ENABLED",
                 "ULTRON_PHASE2B_ENABLED", "ULTRON_PHASE3B_ENABLED",
                 "ULTRON_PHASE4_ENABLED"):
        monkeypatch.delenv(flag, raising=False)
    yield
    wfs._reset_for_test()


def test_flag_off_brief_me_now_falls_through(monkeypatch):
    monkeypatch.delenv("ULTRON_PHASE6_ENABLED", raising=False)
    import briefing_builder as bb
    import briefing_delivery as bd
    bb_compose = MagicMock(return_value="briefing")
    bd_deliver = MagicMock(return_value={})
    monkeypatch.setattr(bb, "compose", bb_compose)
    monkeypatch.setattr(bd, "deliver", bd_deliver)
    voice_engine.parse_voice_command("brief me now")
    bb_compose.assert_not_called()
    bd_deliver.assert_not_called()


def test_flag_on_brief_me_now_invokes_briefing(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE6_ENABLED", "1")
    import briefing_builder as bb
    import briefing_delivery as bd
    bb_compose = MagicMock(return_value="your briefing text")
    bd_deliver = MagicMock(return_value={"voice": {"ok": True}})
    monkeypatch.setattr(bb, "compose", bb_compose)
    monkeypatch.setattr(bd, "deliver", bd_deliver)
    result = voice_engine.parse_voice_command("brief me now")
    bb_compose.assert_called_once()
    bd_deliver.assert_called_once()
    assert result is None  # short-circuited


def test_flag_on_what_is_new_speaks_top_worldfeed(monkeypatch):
    import time as _t
    monkeypatch.setenv("ULTRON_PHASE6_ENABLED", "1")
    wfs.record(WorldEvent(
        title="AAPL up 3%", summary="", url="", source="av",
        ts=_t.time() - 60.0, score=0.9,
    ))
    import briefing_delivery as bd
    bd_deliver = MagicMock(return_value={"voice": {"ok": True}})
    monkeypatch.setattr(bd, "deliver", bd_deliver)
    result = voice_engine.parse_voice_command("what's new in the world")
    bd_deliver.assert_called_once()
    spoken = bd_deliver.call_args[0][0]
    assert "AAPL up 3%" in spoken
    assert result is None


def test_flag_on_no_match_falls_through(monkeypatch):
    monkeypatch.setenv("ULTRON_PHASE6_ENABLED", "1")
    import briefing_builder as bb
    bb_compose = MagicMock()
    monkeypatch.setattr(bb, "compose", bb_compose)
    result = voice_engine.parse_voice_command("what is the time")
    bb_compose.assert_not_called()
    assert result == "TIME"
