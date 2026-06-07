"""Tests for struggle_detector — error-persistence state machine."""
import pytest
import struggle_detector as sd
from struggle_types import ScreenSnapshot, StuckEvent, StuckKind, SensitivityKind


@pytest.fixture(autouse=True)
def _reset():
    sd._reset_for_test()
    yield
    sd._reset_for_test()


def _snap(ts: float, sig: str = "err1", window: str = "Code", text: str = "Some error",
          sensitivity=SensitivityKind.NONE) -> ScreenSnapshot:
    return ScreenSnapshot(ts=ts, active_window=window, error_text=text,
                          error_signature=sig, sensitivity=sensitivity)


def test_no_event_below_threshold():
    sd.ingest(_snap(100.0))
    ev = sd.ingest(_snap(115.0))
    assert ev is None


def test_emit_event_when_persistence_threshold_crossed():
    sd.ingest(_snap(100.0))
    ev = sd.ingest(_snap(135.0))
    assert ev is not None
    assert ev.kind == StuckKind.ERROR_PERSISTENT
    assert ev.duration_seconds >= 35.0


def test_event_only_emitted_once_per_signature():
    sd.ingest(_snap(100.0))
    first = sd.ingest(_snap(135.0))
    assert first is not None
    second = sd.ingest(_snap(160.0))
    assert second is None


def test_error_signature_change_resets_tracking():
    sd.ingest(_snap(100.0, sig="err1"))
    out = sd.ingest(_snap(115.0, sig="err2"))
    assert out is None
    out = sd.ingest(_snap(135.0, sig="err2"))
    assert out is None
    out = sd.ingest(_snap(150.0, sig="err2"))
    assert out is not None


def test_no_event_when_no_error_present():
    snap = _snap(100.0, sig="")
    snap.error_text = ""
    out = sd.ingest(snap)
    assert out is None


def test_no_event_when_sensitivity_high():
    snap = _snap(100.0, sensitivity=SensitivityKind.BANKING)
    sd.ingest(snap)
    snap2 = _snap(140.0, sensitivity=SensitivityKind.BANKING)
    out = sd.ingest(snap2)
    assert out is None


def test_threshold_override():
    sd.ingest(_snap(100.0))
    ev = sd.ingest(_snap(110.0), threshold_seconds=5)
    assert ev is not None
    assert ev.duration_seconds >= 10.0
