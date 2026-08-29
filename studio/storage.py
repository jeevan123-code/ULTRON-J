"""
studio/storage.py — Media storage abstraction.

Generated media must not live in the database, and the code that writes it
must not know whether it lands on a local disk or in an object store. Every
write goes through `MediaStorageProvider`, so moving from local development
to production storage is a config change plus one adapter, not a rewrite of
the generation pipeline.

`LocalStorageProvider` is the only implementation shipped, because it is the
only backend we can exercise here. It is deliberately complete rather than a
stub: real path safety, real metadata, real deletion.

Path safety
-----------
Keys are caller-supplied and end up as filesystem paths, so `_resolve()`
normalises and then verifies containment under the media root. A key like
`../../etc/passwd` raises rather than escaping. This is the one place in the
package where a path traversal could occur, so the check lives here and
nowhere else needs to repeat it.
"""

from __future__ import annotations

import mimetypes
import os
import re
import shutil
import time
from typing import Optional

from .providers.base import MediaStorageProvider

try:
    from config import STUDIO_MEDIA_DIR, STUDIO_STORAGE_BACKEND
except ImportError:  # pragma: no cover
    STUDIO_MEDIA_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "studio_media")
    STUDIO_STORAGE_BACKEND = "local"


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(Exception):
    pass


def sanitize_key(*parts: str) -> str:
    """Build a storage key from untrusted parts.

    Each segment is reduced to a safe character set and `.`/`..` are dropped
    outright, so a key can never climb out of the media root even before
    `_resolve()`'s containment check.
    """
    clean: list[str] = []
    for part in parts:
        for segment in str(part or "").split("/"):
            segment = _SAFE_SEGMENT.sub("_", segment).strip("._")
            if segment and segment not in (".", ".."):
                clean.append(segment[:120])
    if not clean:
        raise StorageError("empty storage key")
    return "/".join(clean)


class LocalStorageProvider(MediaStorageProvider):
    """Filesystem-backed storage rooted at STUDIO_MEDIA_DIR."""

    name = "local"

    def __init__(self, root: str = ""):
        self.root = os.path.abspath(root or STUDIO_MEDIA_DIR)
        os.makedirs(self.root, exist_ok=True)

    def _resolve(self, key: str) -> str:
        if not key:
            raise StorageError("empty storage key")
        path = os.path.abspath(os.path.join(self.root, key))
        # Containment check — the guard that makes caller-supplied keys safe.
        if not (path == self.root or path.startswith(self.root + os.sep)):
            raise StorageError(f"storage key escapes media root: {key!r}")
        return path

    def upload(self, key: str, data: bytes, mime: str = "") -> dict:
        path = self._resolve(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Write to a temp sibling then rename, so a crash mid-write never
        # leaves a truncated asset that the renderer would later choke on.
        tmp = f"{path}.part"
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

        return {
            "key": key,
            "bytes": len(data),
            "mime": mime or mimetypes.guess_type(path)[0] or "application/octet-stream",
            "path": path,
            "created_at": time.time(),
        }

    def upload_file(self, key: str, src_path: str, mime: str = "") -> dict:
        path = self._resolve(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(src_path, path)
        return {
            "key": key,
            "bytes": os.path.getsize(path),
            "mime": mime or mimetypes.guess_type(path)[0] or "application/octet-stream",
            "path": path,
            "created_at": time.time(),
        }

    def download_url(self, key: str, expires_s: int = 3600) -> str:
        """Local files are served by the Studio blueprint, which re-checks
        project ownership. There is no signed-URL concept here, so the route
        does the authorisation instead."""
        return f"/studio/media/{key}"

    def delete(self, key: str) -> bool:
        try:
            path = self._resolve(key)
        except StorageError:
            return False
        try:
            os.unlink(path)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def get_metadata(self, key: str) -> Optional[dict]:
        try:
            path = self._resolve(key)
            stat = os.stat(path)
        except (StorageError, FileNotFoundError, OSError):
            return None
        return {
            "key": key,
            "bytes": stat.st_size,
            "mime": mimetypes.guess_type(path)[0] or "application/octet-stream",
            "modified_at": stat.st_mtime,
            "path": path,
        }

    def local_path(self, key: str) -> Optional[str]:
        try:
            path = self._resolve(key)
        except StorageError:
            return None
        return path if os.path.exists(path) else None

    def exists(self, key: str) -> bool:
        return self.local_path(key) is not None


_BACKENDS = {"local": LocalStorageProvider}
_ACTIVE: Optional[MediaStorageProvider] = None


def get_storage() -> MediaStorageProvider:
    """Return the configured backend.

    An unknown backend name is a configuration error we refuse to paper over
    with a silent fallback — the operator asked for storage we do not have,
    and quietly writing to local disk instead would lose their media.
    """
    global _ACTIVE
    if _ACTIVE is not None:
        return _ACTIVE

    backend = (STUDIO_STORAGE_BACKEND or "local").lower()
    factory = _BACKENDS.get(backend)
    if factory is None:
        raise StorageError(
            f"STUDIO_STORAGE_BACKEND='{backend}' has no adapter. "
            f"Available: {', '.join(sorted(_BACKENDS))}. "
            f"Implement MediaStorageProvider and register it in studio/storage.py."
        )
    _ACTIVE = factory()
    return _ACTIVE


def register_backend(name: str, factory) -> None:
    """Hook for future adapters (S3, GCS, R2) without touching call sites."""
    _BACKENDS[name.lower()] = factory


def describe_storage() -> dict:
    try:
        storage = get_storage()
    except StorageError as exc:
        return {"backend": STUDIO_STORAGE_BACKEND, "ok": False, "error": str(exc)}

    info = {"backend": storage.name, "ok": True}
    if isinstance(storage, LocalStorageProvider):
        info["root"] = storage.root
        try:
            usage = shutil.disk_usage(storage.root)
            info["free_bytes"] = usage.free
            info["total_bytes"] = usage.total
        except OSError:
            pass
    return info
