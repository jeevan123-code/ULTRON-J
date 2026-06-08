"""Shortcut registry — JSON-backed CRUD store.

Single file at `_REGISTRY_PATH` holds an array of Shortcut records.
Re-teaching the same normalised term overwrites the existing entry.
"""
import json
import os
import threading
from typing import Iterator, List, Optional

from shortcut_types import Shortcut


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_REGISTRY_PATH = os.path.join(_BASE_DIR, "shortcuts", "shortcuts.json")

_lock = threading.RLock()
_cache: List[Shortcut] = []
_loaded = False


def _ensure_dir() -> None:
    os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)


def _persist() -> None:
    try:
        _ensure_dir()
        with open(_REGISTRY_PATH, "w") as f:
            json.dump([s.to_dict() for s in _cache], f, indent=2)
    except Exception:
        pass


def _load_from_disk() -> None:
    global _cache, _loaded
    with _lock:
        if not os.path.exists(_REGISTRY_PATH):
            _cache = []
            _loaded = True
            return
        try:
            with open(_REGISTRY_PATH) as f:
                data = json.load(f)
            _cache = [Shortcut.from_dict(d) for d in data]
            _loaded = True
        except Exception:
            _cache = []
            _loaded = True


def _ensure_loaded() -> None:
    with _lock:
        if not _loaded:
            _load_from_disk()


def _reset_for_test() -> None:
    global _cache, _loaded
    with _lock:
        _cache = []
        _loaded = True
        try:
            if os.path.exists(_REGISTRY_PATH):
                os.remove(_REGISTRY_PATH)
        except Exception:
            pass


def _reset_in_memory_for_test() -> None:
    """Wipe in-memory only; leave disk intact. Test helper."""
    global _cache, _loaded
    with _lock:
        _cache = []
        _loaded = False


def _normalise(term: str) -> str:
    return (term or "").strip().lower()


def teach(shortcut: Shortcut) -> Shortcut:
    """Persist a shortcut. Overwrites any existing entry with the same normalised term."""
    if not shortcut.term or not shortcut.term.strip():
        raise ValueError("Shortcut.term must be a non-empty string")
    if not shortcut.canonical or not shortcut.canonical.strip():
        raise ValueError("Shortcut.canonical must be a non-empty string")

    key = _normalise(shortcut.term)
    with _lock:
        _ensure_loaded()
        for i, existing in enumerate(_cache):
            if _normalise(existing.term) == key:
                _cache.pop(i)
                break
        _cache.append(shortcut)
        _persist()
    return shortcut


def get(term: str) -> Optional[Shortcut]:
    """Look up by term (case/whitespace-insensitive)."""
    key = _normalise(term)
    if not key:
        return None
    with _lock:
        _ensure_loaded()
        for s in _cache:
            if _normalise(s.term) == key:
                return s
    return None


def forget(term: str) -> bool:
    """Remove a shortcut. Returns True if something was removed."""
    key = _normalise(term)
    if not key:
        return False
    with _lock:
        _ensure_loaded()
        for i, s in enumerate(_cache):
            if _normalise(s.term) == key:
                _cache.pop(i)
                _persist()
                return True
    return False


def list_all() -> List[Shortcut]:
    """Return every persisted Shortcut."""
    with _lock:
        _ensure_loaded()
        return list(_cache)


def iter_terms() -> Iterator[str]:
    """Yield every normalised term."""
    with _lock:
        _ensure_loaded()
        for s in _cache:
            yield _normalise(s.term)
