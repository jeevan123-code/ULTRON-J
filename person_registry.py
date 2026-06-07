"""Person registry — JSON-backed multi-person store.

Each registered person lives at `_PERSONS_DIR/{slug}.json`. The slug is derived
from `Person.slug_for(name)`. Re-registering the same slug overwrites the file.

This module is intentionally side-effect free at import time: the persons
directory is created lazily on first write.
"""
import json
import os
import threading
from typing import Iterator, List, Optional, Tuple

from person_types import Person


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PERSONS_DIR = os.path.join(_BASE_DIR, "voice_identity", "persons")

_lock = threading.RLock()


def _ensure_dir() -> None:
    os.makedirs(_PERSONS_DIR, exist_ok=True)


def _path_for_slug(slug: str) -> str:
    return os.path.join(_PERSONS_DIR, f"{slug}.json")


def register(person: Person) -> Person:
    """Persist a Person to disk under its slug. Overwrites on conflict."""
    if not person.name or not person.name.strip():
        raise ValueError("Person.name must be a non-empty string")
    slug = Person.slug_for(person.name)
    if not slug:
        raise ValueError(f"Could not derive slug from name={person.name!r}")
    with _lock:
        _ensure_dir()
        with open(_path_for_slug(slug), "w") as f:
            json.dump(person.to_dict(), f, indent=2)
    return person


def get(name: str) -> Optional[Person]:
    """Look up a person by name (case- and whitespace-insensitive)."""
    slug = Person.slug_for(name or "")
    if not slug:
        return None
    path = _path_for_slug(slug)
    with _lock:
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            return None
    try:
        return Person.from_dict(data)
    except Exception:
        return None


def delete(name: str) -> bool:
    """Remove a registered person. Returns True if a file was removed."""
    slug = Person.slug_for(name or "")
    if not slug:
        return False
    path = _path_for_slug(slug)
    with _lock:
        if not os.path.exists(path):
            return False
        try:
            os.remove(path)
            return True
        except Exception:
            return False


def list_all() -> List[Person]:
    """Return every persisted Person, skipping unreadable files."""
    with _lock:
        if not os.path.isdir(_PERSONS_DIR):
            return []
        files = sorted(f for f in os.listdir(_PERSONS_DIR) if f.endswith(".json"))
    out: List[Person] = []
    for fname in files:
        path = os.path.join(_PERSONS_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            out.append(Person.from_dict(data))
        except Exception:
            continue
    return out


def iter_voiceprints() -> Iterator[Tuple[str, List[float]]]:
    """Yield (name, voiceprint) for every registered person."""
    for p in list_all():
        yield p.name, list(p.voiceprint)
