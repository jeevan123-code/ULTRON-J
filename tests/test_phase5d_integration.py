"""End-to-end Phase 5d: stuck event recorded -> mood reflects -> tts redacts."""
from unittest.mock import patch, MagicMock
import datetime
import pytest

import voice_engine as ve
import screen_watcher as sw
import struggle_detector as sd
import struggle_counter as sc
import room_awareness as ra
import person_registry as reg

from struggle_types import ScreenSnapshot, SensitivityKind
from person_types import Person, Relation


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "_PERSONS_DIR", str(tmp_path / "persons"))
    ra._reset_for_test()
    sd._reset_for_test()
    sc._reset_for_test()
    monkeypatch.setenv("ULTRON_PHASE5D_ENABLED", "1")
    monkeypatch.delenv("ULTRON_EYES_CLOSED", raising=False)
    yield
    ra._reset_for_test()
    sd._reset_for_test()
    sc._reset_for_test()


def _capture_tts_call(text, *, mood="FOCUSED", provider="edge"):
    """Run voice_engine.tts with every backend patched out, capturing the
    text that reaches prepare_for_tts. Returns the captured text."""
    captured = {}

    def fake_prepare(t):
        captured["text"] = t
        return "OK"

    with patch.object(ve, "prepare_for_tts", fake_prepare), \
         patch.object(ve, "_tts_edge", lambda t, m: b""), \
         patch.object(ve, "_get_cached", lambda *a, **kw: None), \
         patch.object(ve, "_set_cached", lambda *a, **kw: None), \
         patch.object(ve, "_log_voice", lambda *a, **kw: None):
        ve.tts(text, mood=mood, provider=provider)

    return captured.get("text", "")


def test_stuck_event_recorded_into_counter_via_screen_watcher():
    """Two snapshots of the same error 40s apart -> struggle_detector emits ->
    screen_watcher records into struggle_counter."""
    snap1 = ScreenSnapshot(ts=100.0, active_window="Code", error_text="X",
                           error_signature="x", sensitivity=SensitivityKind.NONE)
    snap2 = ScreenSnapshot(ts=140.0, active_window="Code", error_text="X",
                           error_signature="x", sensitivity=SensitivityKind.NONE)
    with patch.object(sw, "take_snapshot", MagicMock(side_effect=[snap1, snap2])):
        sw._tick()
        sw._tick()
    snap = sc._snapshot_for_test()
    assert snap == [140.0]


def test_tts_redacts_secrets_when_stranger_in_room():
    ra.record_voice("_stranger")
    out = _capture_tts_call("My password=hunter2 is wrong.")
    assert "hunter2" not in out
    assert "[redacted]" in out


def test_tts_preserves_secrets_in_private_room():
    """Empty room -> private mode -> no redaction."""
    out = _capture_tts_call("My password=hunter2 is fine here.")
    assert "hunter2" in out


def test_tts_softens_tone_when_late_hour(monkeypatch):
    """Force mood_tracker._now() to return 23:00 -> TIRED -> soft preamble."""
    import mood_tracker as mt
    monkeypatch.setattr(mt, "_now", lambda: datetime.datetime(2026, 6, 8, 23, 0, 0))
    out = _capture_tts_call("Build finished.")
    assert out.startswith("Take your time, sir.")


def test_tts_frustrated_when_many_recent_struggles(monkeypatch):
    """Force 3 struggle events into the counter -> FRUSTRATED -> drop 'Sir,' filler."""
    import time as _time
    now_ts = _time.time()
    sc.record_struggle(ts=now_ts - 60)
    sc.record_struggle(ts=now_ts - 30)
    sc.record_struggle(ts=now_ts - 10)
    out = _capture_tts_call("Sir, the file is corrupted.")
    assert not out.lower().startswith("sir,")
    assert "file is corrupted" in out


def test_tts_combined_stranger_plus_tired_redacts_and_softens(monkeypatch):
    ra.record_voice("_stranger")
    import mood_tracker as mt
    monkeypatch.setattr(mt, "_now", lambda: datetime.datetime(2026, 6, 8, 23, 0, 0))
    out = _capture_tts_call("Sir, the password=hunter2 unlocks /home/jeevan/vault.json.")
    assert "hunter2" not in out
    assert "/home/jeevan/vault.json" not in out
    assert out.startswith("Take your time, sir.")


def test_tts_flag_off_leaves_text_unchanged(monkeypatch):
    """When ULTRON_PHASE5D_ENABLED is OFF, no modulation happens."""
    monkeypatch.setenv("ULTRON_PHASE5D_ENABLED", "0")
    ra.record_voice("_stranger")
    out = _capture_tts_call("My password=hunter2.")
    assert "hunter2" in out
