"""Struggle Detector.

Pure-state machine. Takes a sequence of ScreenSnapshots and decides whether
the same error has been visible long enough to count as "stuck".

Single-error tracking only:
  - first sighting starts a timer
  - subsequent sightings of the same signature update the timer
  - a signature change resets tracking to the new signature
  - once a signature has emitted ONE event, further sightings are silenced
    until the signature changes (no spam)

Sensitive screens (banking / password / secret_file) are silently ignored.
"""
import threading
from typing import Optional

from struggle_types import (
    ScreenSnapshot,
    StuckEvent,
    StuckKind,
    SensitivityKind,
)


_DEFAULT_THRESHOLD_SECONDS = 30

_lock = threading.RLock()
_current_signature: str = ""
_first_seen_ts: float = 0.0
_last_seen_ts: float = 0.0
_already_emitted: bool = False


def _reset_for_test() -> None:
    global _current_signature, _first_seen_ts, _last_seen_ts, _already_emitted
    with _lock:
        _current_signature = ""
        _first_seen_ts = 0.0
        _last_seen_ts = 0.0
        _already_emitted = False


def _reset_tracking_to(signature: str, ts: float) -> None:
    global _current_signature, _first_seen_ts, _last_seen_ts, _already_emitted
    _current_signature = signature
    _first_seen_ts = ts
    _last_seen_ts = ts
    _already_emitted = False


def ingest(snapshot: ScreenSnapshot,
           threshold_seconds: int = _DEFAULT_THRESHOLD_SECONDS) -> Optional[StuckEvent]:
    """Feed a snapshot. Emit a StuckEvent the first time the same error has
    persisted for >= threshold_seconds. Returns None otherwise."""
    if snapshot.sensitivity != SensitivityKind.NONE:
        return None
    if not snapshot.error_signature or not snapshot.error_text:
        return None

    with _lock:
        global _last_seen_ts, _already_emitted

        if snapshot.error_signature != _current_signature:
            _reset_tracking_to(snapshot.error_signature, snapshot.ts)
            return None

        _last_seen_ts = snapshot.ts
        if _already_emitted:
            return None
        if (snapshot.ts - _first_seen_ts) < threshold_seconds:
            return None

        _already_emitted = True
        return StuckEvent(
            kind=StuckKind.ERROR_PERSISTENT,
            first_seen_ts=_first_seen_ts,
            last_seen_ts=_last_seen_ts,
            duration_seconds=_last_seen_ts - _first_seen_ts,
            snapshot=snapshot,
        )
