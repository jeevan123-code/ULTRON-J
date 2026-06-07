"""Research queue — priority + dedupe + JSON persistence.

Thread-safe. JSON-backed at _QUEUE_PATH so the queue survives ULTRON restart.
"""
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional


_QUEUE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research_queue.json")
_DEFAULT_DEDUPE_TTL_SECONDS = 3600  # 1 hour

_lock = threading.RLock()
_pending: List[Dict[str, Any]] = []
_in_flight: Dict[str, Dict[str, Any]] = {}
_dedupe_seen: Dict[str, float] = {}


def _now() -> float:
    return time.time()


def _normalize(topic: str) -> str:
    return (topic or "").strip().lower()


def _persist() -> None:
    try:
        data = {"pending": _pending, "dedupe": _dedupe_seen, "saved_at": _now()}
        with open(_QUEUE_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _load_from_disk() -> None:
    global _pending, _dedupe_seen
    try:
        if not os.path.exists(_QUEUE_PATH):
            return
        with open(_QUEUE_PATH) as f:
            data = json.load(f)
        with _lock:
            _pending = list(data.get("pending", []))
            _dedupe_seen = dict(data.get("dedupe", {}))
    except Exception:
        pass


def _reset_for_test() -> None:
    global _pending, _in_flight, _dedupe_seen
    with _lock:
        _pending = []
        _in_flight = {}
        _dedupe_seen = {}
        try:
            if os.path.exists(_QUEUE_PATH):
                os.remove(_QUEUE_PATH)
        except Exception:
            pass


def _reset_in_memory_for_test() -> None:
    global _pending, _in_flight, _dedupe_seen
    with _lock:
        _pending = []
        _in_flight = {}
        _dedupe_seen = {}


def _prune_dedupe() -> None:
    now = _now()
    expired = [k for k, exp in _dedupe_seen.items() if exp <= now]
    for k in expired:
        _dedupe_seen.pop(k, None)


def enqueue(topic: str, priority: int = 1,
            dedupe_ttl_seconds: int = _DEFAULT_DEDUPE_TTL_SECONDS,
            metadata: Optional[Dict[str, Any]] = None) -> bool:
    topic = (topic or "").strip()
    if not topic:
        return False
    norm = _normalize(topic)
    with _lock:
        _prune_dedupe()
        if dedupe_ttl_seconds > 0 and norm in _dedupe_seen:
            return False
        job = {
            "id": str(uuid.uuid4()),
            "topic": topic,
            "priority": int(priority),
            "ts": _now(),
            "metadata": dict(metadata or {}),
        }
        _pending.append(job)
        _pending.sort(key=lambda j: (-j["priority"], j["ts"]))
        if dedupe_ttl_seconds > 0:
            _dedupe_seen[norm] = _now() + dedupe_ttl_seconds
        _persist()
        return True


def peek() -> Optional[Dict[str, Any]]:
    with _lock:
        return dict(_pending[0]) if _pending else None


def pop() -> Optional[Dict[str, Any]]:
    with _lock:
        if not _pending:
            return None
        job = _pending.pop(0)
        _in_flight[job["id"]] = job
        _persist()
        return dict(job)


def done(job_id: str) -> bool:
    with _lock:
        existed = job_id in _in_flight
        _in_flight.pop(job_id, None)
        return existed


def snapshot() -> List[Dict[str, Any]]:
    with _lock:
        return [dict(j) for j in _pending]


_load_from_disk()
