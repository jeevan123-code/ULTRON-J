"""Tests for briefing_delivery — fan-out to telegram + voice."""
from unittest.mock import MagicMock

import pytest

import briefing_delivery as bd


def test_telegram_channel_calls_send_message(monkeypatch):
    fake_send = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(bd, "_telegram_send", fake_send)
    result = bd.deliver("hello", ["telegram"])
    fake_send.assert_called_once_with("hello")
    assert result["telegram"]["ok"] is True


def test_voice_channel_calls_tts(monkeypatch):
    fake_tts = MagicMock(return_value=(b"audio", "edge"))
    monkeypatch.setattr(bd, "_voice_say", fake_tts)
    result = bd.deliver("hello", ["voice"])
    fake_tts.assert_called_once_with("hello")
    assert result["voice"]["ok"] is True
    assert result["voice"]["provider"] == "edge"


def test_unknown_channel_returns_skipped(monkeypatch):
    result = bd.deliver("hello", ["fax"])
    assert result["fax"]["skipped"] is True


def test_failure_on_one_channel_does_not_abort_others(monkeypatch):
    monkeypatch.setattr(bd, "_telegram_send",
                        MagicMock(side_effect=RuntimeError("token missing")))
    monkeypatch.setattr(bd, "_voice_say",
                        MagicMock(return_value=(b"audio", "kokoro")))
    result = bd.deliver("hello", ["telegram", "voice"])
    assert result["telegram"]["ok"] is False
    assert "token missing" in result["telegram"]["error"]
    assert result["voice"]["ok"] is True


def test_empty_channel_list_returns_empty(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr(bd, "_telegram_send", fake_send)
    result = bd.deliver("hello", [])
    fake_send.assert_not_called()
    assert result == {}
