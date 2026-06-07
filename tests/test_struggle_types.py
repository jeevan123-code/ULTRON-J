"""Tests for struggle_types dataclasses."""
from struggle_types import (
    ScreenSnapshot, StuckEvent, StuckKind, SensitivityKind,
)


def test_stuck_kind_values():
    assert StuckKind.ERROR_PERSISTENT.value == "error_persistent"
    assert StuckKind.IDLE_ON_ERROR.value == "idle_on_error"


def test_sensitivity_kind_values():
    assert SensitivityKind.BANKING.value == "banking"
    assert SensitivityKind.PASSWORD_FIELD.value == "password_field"
    assert SensitivityKind.NONE.value == "none"


def test_screen_snapshot_construction():
    snap = ScreenSnapshot(
        ts=1700000000.0,
        active_window="Code - main.py",
        error_text="NameError: name 'x' is not defined",
        error_signature="nameerror:nameisnotdefined",
        sensitivity=SensitivityKind.NONE,
    )
    assert snap.error_signature == "nameerror:nameisnotdefined"
    d = snap.to_dict()
    assert d["sensitivity"] == "none"


def test_stuck_event_construction():
    snap = ScreenSnapshot(ts=1700000000.0, active_window="Code", error_text="X",
                          error_signature="x", sensitivity=SensitivityKind.NONE)
    ev = StuckEvent(
        kind=StuckKind.ERROR_PERSISTENT,
        first_seen_ts=1700000000.0,
        last_seen_ts=1700000035.0,
        duration_seconds=35.0,
        snapshot=snap,
    )
    assert ev.duration_seconds == 35.0
    assert ev.snapshot.error_signature == "x"
    assert ev.kind == StuckKind.ERROR_PERSISTENT
    d = ev.to_dict()
    assert d["kind"] == "error_persistent"
    assert d["snapshot"]["error_signature"] == "x"
