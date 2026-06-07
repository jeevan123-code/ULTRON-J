"""End-to-end Phase 3a: screen_engine -> watcher -> detector -> log."""
from unittest.mock import patch, MagicMock
import time
import pytest

import screen_watcher as sw
import struggle_detector as sd


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "_LOG_PATH", str(tmp_path / "ultron_log.txt"))
    monkeypatch.delenv("ULTRON_EYES_CLOSED", raising=False)
    sd._reset_for_test()
    yield
    sd._reset_for_test()


def _fake_engine(error_text: str, active_window: str = "Code - main.py"):
    return MagicMock(detect_errors_on_screen=MagicMock(return_value={
        "has_error": bool(error_text),
        "error_text": error_text,
        "active_window": active_window,
    }))


def test_persistent_error_emits_log_line(monkeypatch):
    """Same error across two ticks separated by >threshold emits a stuck log line."""
    monkeypatch.setattr(sw, "_get_screen_engine", lambda: _fake_engine("NameError: x"))

    sw._tick()
    fake_now = time.time() + 60
    with patch("time.time", return_value=fake_now):
        sw._tick()

    with open(sw._LOG_PATH) as f:
        log = f.read()
    assert "[phase3a][stuck]" in log
    assert "error_persistent" in log


def test_sensitive_screen_does_not_emit(monkeypatch):
    """Banking-flavoured screen never produces a stuck event."""
    eng = _fake_engine("Some error", active_window="Online Banking - HDFC")
    monkeypatch.setattr(sw, "_get_screen_engine", lambda: eng)

    sw._tick()
    fake_now = time.time() + 60
    with patch("time.time", return_value=fake_now):
        sw._tick()

    log_path = sw._LOG_PATH
    log = open(log_path).read() if __import__("os").path.exists(log_path) else ""
    assert "[phase3a][stuck]" not in log


def test_eyes_closed_skips_everything(monkeypatch):
    eng_mock = MagicMock(detect_errors_on_screen=MagicMock())
    monkeypatch.setattr(sw, "_get_screen_engine", lambda: eng_mock)
    monkeypatch.setenv("ULTRON_EYES_CLOSED", "1")
    sw._tick()
    eng_mock.detect_errors_on_screen.assert_not_called()
