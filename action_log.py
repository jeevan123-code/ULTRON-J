"""Phase 3c action log — thread-safe rolling buffer of user actions.

Mirrors the `struggle_counter` / `shortcut_registry` pattern: in-memory deque
with optional JSON persistence at `_PATH`. Records every accepted event;
`improvement_suggester` analyses the rolling window for repetitions.
"""
import json
import os
import threading
import time
from collections import deque
from typing import Deque, List, Optional

from action_types import ActionEvent, ActionKind


MAX_BUFFER = 256
_DEFAULT_WINDOW_SECONDS = 3600  # 1 hour

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_BASE_DIR, "action_log.json")

_lock = threading.RLock()
_buffer: Deque[ActionEvent] = deque(maxlen=MAX_BUFFER)
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
            _buffer = deque(
                (ActionEvent.from_dict(d) for d in data),
                maxlen=MAX_BUFFER,
            )
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
    """Wipe in-memory only; leave disk intact."""
    global _buffer, _loaded
    with _lock:
        _buffer = deque(maxlen=MAX_BUFFER)
        _loaded = False


def _snapshot_for_test() -> List[ActionEvent]:
    with _lock:
        return list(_buffer)


def record(event: ActionEvent) -> None:
    """Append a new ActionEvent and persist to disk."""
    with _lock:
        _ensure_loaded()
        _buffer.append(event)
        _persist()


def recent(now: Optional[float] = None,
           within_seconds: int = _DEFAULT_WINDOW_SECONDS,
           kind: Optional[ActionKind] = None) -> List[ActionEvent]:
    """Return events within `within_seconds` of `now`, optionally filtered by kind."""
    cutoff_now = _now() if now is None else float(now)
    with _lock:
        _ensure_loaded()
        return [
            e for e in _buffer
            if cutoff_now - e.ts <= within_seconds
            and (kind is None or e.kind == kind)
        ]


def recent_count(now: Optional[float] = None,
                 within_seconds: int = _DEFAULT_WINDOW_SECONDS,
                 kind: Optional[ActionKind] = None) -> int:
    """Count events within the window; optional kind filter."""
    return len(recent(now=now, within_seconds=within_seconds, kind=kind))
