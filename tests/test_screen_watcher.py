"""Tests for screen_watcher — polling + sensitive-mode pause + off-switch."""
from unittest.mock import patch, MagicMock
import os
import pytest
import screen_watcher as sw
import struggle_detector as sd
from struggle_types import StuckEvent, StuckKind, SensitivityKind


@pytest.fixture(autouse=True)
def _reset():
    sd._reset_for_test()
    sw._reset_for_test()
    yield
    sd._reset_for_test()
    sw._reset_for_test()


def test_classify_sensitivity_detects_password_field():
    title = "Login - Bank of America"
    text = "Enter your password\n••••••"
    assert sw.classify_sensitivity(title, text) == SensitivityKind.BANKING


def test_classify_sensitivity_detects_secret_file():
    title = "Code - .env"
    text = "SECRET_KEY=abc"
    assert sw.classify_sensitivity(title, text) == SensitivityKind.SECRET_FILE


def test_classify_sensitivity_default_none():
    assert sw.classify_sensitivity("Code - main.py", "def hello():") == SensitivityKind.NONE


def test_normalize_error_signature_collapses_whitespace_and_lowercases():
    sig = sw.normalize_error_signature("  NameError:  name 'x'   is not defined  ")
    assert sig == "nameerror:nameisnotdefined"


def test_take_snapshot_uses_screen_engine(monkeypatch):
    fake_result = {
        "has_error": True,
        "error_text": "TypeError: foo",
        "active_window": "Code - main.py",
    }
    fake_screen_engine = MagicMock(detect_errors_on_screen=MagicMock(return_value=fake_result))
    monkeypatch.setattr(sw, "_get_screen_engine", lambda: fake_screen_engine)
    snap = sw.take_snapshot()
    assert snap.error_text == "TypeError: foo"
    assert snap.active_window == "Code - main.py"
    assert snap.error_signature == "typeerror:foo"


def test_take_snapshot_returns_none_when_screen_engine_fails(monkeypatch):
    fake_screen_engine = MagicMock(detect_errors_on_screen=MagicMock(side_effect=RuntimeError("X")))
    monkeypatch.setattr(sw, "_get_screen_engine", lambda: fake_screen_engine)
    assert sw.take_snapshot() is None


def test_tick_emits_event_to_log_on_stuck(monkeypatch, tmp_path):
    log_path = tmp_path / "ultron_log.txt"
    monkeypatch.setattr(sw, "_LOG_PATH", str(log_path))

    from struggle_types import ScreenSnapshot
    snap1 = ScreenSnapshot(ts=100.0, active_window="Code", error_text="X",
                           error_signature="x", sensitivity=SensitivityKind.NONE)
    snap2 = ScreenSnapshot(ts=140.0, active_window="Code", error_text="X",
                           error_signature="x", sensitivity=SensitivityKind.NONE)
    monkeypatch.setattr(sw, "take_snapshot", MagicMock(side_effect=[snap1, snap2]))

    sw._tick()
    sw._tick()
    assert log_path.exists()
    content = log_path.read_text()
    assert "[phase3a]" in content
    assert "stuck" in content.lower()


def test_eyes_closed_flag_skips_polling(monkeypatch):
    monkeypatch.setenv("ULTRON_EYES_CLOSED", "1")
    take = MagicMock()
    monkeypatch.setattr(sw, "take_snapshot", take)
    sw._tick()
    take.assert_not_called()
