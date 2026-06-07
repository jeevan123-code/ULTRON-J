"""Conversation Listener — thread-safe rolling buffer of recent utterances.

Phase 2b auto-research polls `drain_unprocessed()` to find utterances it
hasn't yet evaluated for research-worthiness.
"""
import threading
import time
from collections import deque
from typing import Any, Dict, List


MAX_BUFFER = 32

_lock = threading.RLock()
_buffer: deque = deque(maxlen=MAX_BUFFER)


def _reset_for_test() -> None:
    with _lock:
        _buffer.clear()


def record(text: str) -> None:
    """Push an utterance into the buffer. No-op on empty/whitespace input."""
    if not text or not text.strip():
        return
    with _lock:
        _buffer.append({"text": text.strip(), "ts": time.time(), "processed": False})


def snapshot() -> List[Dict[str, Any]]:
    """Return a copy of every utterance currently in the buffer."""
    with _lock:
        return [dict(u) for u in _buffer]


def drain_unprocessed() -> List[Dict[str, Any]]:
    """Return all unprocessed utterances and mark them processed."""
    out: List[Dict[str, Any]] = []
    with _lock:
        for u in _buffer:
            if not u["processed"]:
                out.append(dict(u))
                u["processed"] = True
    return out
