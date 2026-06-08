"""Struggle Counter — thread-safe rolling log of struggle timestamps.

Phase 5d uses this to feed `mood_tracker.current_mood(recent_struggles=…)` so
ULTRON's spoken-text mood reflects how rough the last hour has been.

Pure data — no I/O, no integrations. `screen_watcher._tick` records into
this module after each StuckEvent (flag-gated by ULTRON_PHASE5D_ENABLED).
"""
import threading
import time
from collections import deque
from typing import Deque, List, Optional


MAX_BUFFER = 128
_DEFAULT_WINDOW_SECONDS = 3600  # 1 hour

_lock = threading.RLock()
_buffer: Deque[float] = deque(maxlen=MAX_BUFFER)


def _now() -> float:
    return time.time()


def _reset_for_test() -> None:
    with _lock:
        _buffer.clear()


def _snapshot_for_test() -> List[float]:
    with _lock:
        return list(_buffer)


def record_struggle(ts: Optional[float] = None) -> None:
    """Record one struggle event at the given timestamp (default: now)."""
    with _lock:
        _buffer.append(_now() if ts is None else float(ts))


def recent_count(now: Optional[float] = None,
                 within_seconds: int = _DEFAULT_WINDOW_SECONDS) -> int:
    """Count entries within `within_seconds` of `now`. Inclusive boundary."""
    cutoff_now = _now() if now is None else float(now)
    with _lock:
        return sum(1 for ts in _buffer if cutoff_now - ts <= within_seconds)
