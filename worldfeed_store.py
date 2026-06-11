"""Phase 6 worldfeed store — ranked JSON-backed feed of WorldEvents.

Mirrors `action_log.py` patterns. The poller writes through; the briefing
builder and voice hook read via `recent(top_n=...)`.
"""
import json
import os
import threading
import time
from collections import deque
from typing import Deque, List, Optional

from world_event_types import WorldEvent


MAX_BUFFER = 200
_DEFAULT_WINDOW_SECONDS = 24 * 3600  # 24 hours

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_BASE_DIR, "worldfeed.json")

_lock = threading.RLock()
_buffer: Deque[WorldEvent] = deque(maxlen=MAX_BUFFER)
_loaded = False


def _now() -> float:
    return time.time()


def _persist() -> None:
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, "w") as f:
            json.dump([e.to_dict() for e in _buffer], f, indent=2)
    except Exception:
        pass


def _load_from_disk() -> None:
    global _buffer, _loaded
    with _lock:
        if not os.path.exists(_PATH):
            _buffer = deque(maxlen=MAX_BUFFER)
            _loaded = True
            return
        try:
            with open(_PATH) as f:
                data = json.load(f)
            _buffer = deque((WorldEvent.from_dict(d) for d in data), maxlen=MAX_BUFFER)
            _loaded = True
        except Exception:
            _buffer = deque(maxlen=MAX_BUFFER)
            _loaded = True


def _ensure_loaded() -> None:
    with _lock:
        if not _loaded:
            _load_from_disk()


def _reset_for_test() -> None:
    global _buffer, _loaded
    with _lock:
        _buffer = deque(maxlen=MAX_BUFFER)
        _loaded = True
        try:
            if os.path.exists(_PATH):
                os.remove(_PATH)
        except Exception:
            pass


def _reset_in_memory_for_test() -> None:
    global _buffer, _loaded
    with _lock:
        _buffer = deque(maxlen=MAX_BUFFER)
        _loaded = False


def _snapshot_for_test() -> List[WorldEvent]:
    with _lock:
        return list(_buffer)


def record(event: WorldEvent) -> None:
    """Append a new WorldEvent and persist."""
    with _lock:
        _ensure_loaded()
        _buffer.append(event)
        _persist()


def recent(now: Optional[float] = None,
           within_seconds: int = _DEFAULT_WINDOW_SECONDS,
           top_n: Optional[int] = None) -> List[WorldEvent]:
    """Return events within the window. If top_n given, sort by score desc and slice."""
    cutoff_now = _now() if now is None else float(now)
    with _lock:
        _ensure_loaded()
        items = [e for e in _buffer if cutoff_now - e.ts <= within_seconds]
    if top_n is not None:
        items = sorted(items, key=lambda e: e.score, reverse=True)[:top_n]
    return items
