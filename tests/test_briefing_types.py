"""Tests for briefing_types — BriefingSchedule dataclass."""
import pytest

from briefing_types import BriefingSchedule


def test_construct_briefing_schedule():
    s = BriefingSchedule(
        id="morning", cron_expr="0 8 * * *",
        channels=["telegram", "voice"], include_worldfeed=True,
        created_at=100.0,
    )
    assert s.id == "morning"
    assert "telegram" in s.channels
    assert s.include_worldfeed is True


def test_defaults():
    s = BriefingSchedule(id="x", cron_expr="* * * * *", created_at=0.0)
    assert s.channels == ["telegram"]
    assert s.include_worldfeed is True


def test_to_dict_roundtrip():
    s = BriefingSchedule(
        id="evening", cron_expr="0 21 * * *",
        channels=["voice"], include_worldfeed=False, created_at=10.0,
    )
    back = BriefingSchedule.from_dict(s.to_dict())
    assert back == s
