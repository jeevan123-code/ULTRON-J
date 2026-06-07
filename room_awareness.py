"""Room Awareness — thread-safe rolling log of recent voices.

Phase 5a populates this whenever a known speaker is identified. Phase 5b will
read `who_is_in_the_room()` to drive privacy-circle behavior.
"""
import threading
import time
from collections import deque
from typing import Deque, List, Optional, Tuple


MAX_BUFFER = 128

_lock = threading.RLock()
_buffer: Deque[Tuple[str, float]] = deque(maxlen=MAX_BUFFER)


def _now() -> float:
    return time.time()


def _reset_for_test() -> None:
    with _lock:
        _buffer.clear()


def _snapshot_for_test() -> List[Tuple[str, float]]:
    with _lock:
        return list(_buffer)


def record_voice(name: str, ts: Optional[float] = None) -> None:
    """Record a voice attribution. No-op on empty/whitespace name."""
    if not name or not name.strip():
        return
    with _lock:
        _buffer.append((name.strip(), _now() if ts is None else float(ts)))


def last_seen(name: str) -> Optional[float]:
    """Return the most recent timestamp a name was recorded, or None."""
    if not name or not name.strip():
        return None
    target = name.strip()
    with _lock:
        for n, ts in reversed(_buffer):
            if n == target:
                return ts
    return None


def who_is_in_the_room(now: Optional[float] = None,
                       within_seconds: int = 300) -> List[str]:
    """Distinct names heard within `within_seconds` of `now` (default: real now)."""
    cutoff_now = _now() if now is None else float(now)
    seen: List[str] = []
    with _lock:
        for n, ts in _buffer:
            if cutoff_now - ts <= within_seconds and n not in seen:
                seen.append(n)
    return seen
