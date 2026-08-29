"""
studio/providers/http.py — Shared HTTP plumbing for provider adapters.

Centralises the three things every adapter would otherwise reimplement
badly: timeouts, retry-worthy error classification, and turning an HTTP
failure into a `ProviderError` the job worker can reason about.

Adapters never call `requests` directly — a bare call with no timeout is
how a web worker ends up wedged behind a provider outage.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .base import ProviderError, RateLimited

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover - requests is a hard dependency
    requests = None
    REQUESTS_AVAILABLE = False


DEFAULT_TIMEOUT = (10, 120)   # (connect, read)

#: Status codes worth retrying: transient server faults and rate limits.
RETRYABLE_CODES = {408, 425, 429, 500, 502, 503, 504}


def request(method: str, url: str, *, provider: str = "",
            timeout: Any = DEFAULT_TIMEOUT, **kwargs):
    """Perform an HTTP call, mapping failures onto ProviderError.

    Network-level failures (DNS, connect, read timeout) are retryable —
    they say nothing about whether the request was valid. 4xx other than
    429/408 are not: retrying a malformed request just burns quota.
    """
    if not REQUESTS_AVAILABLE:
        raise ProviderError(f"{provider}: 'requests' is not installed", retryable=False)

    try:
        resp = requests.request(method, url, timeout=timeout, **kwargs)
    except requests.exceptions.Timeout as exc:
        raise ProviderError(f"{provider}: request timed out", retryable=True) from exc
    except requests.exceptions.ConnectionError as exc:
        raise ProviderError(f"{provider}: connection failed ({exc})", retryable=True) from exc
    except Exception as exc:  # noqa: BLE001 - adapters must never leak raw errors
        raise ProviderError(f"{provider}: request error ({exc})", retryable=False) from exc

    if resp.status_code == 429:
        retry_after = 0.0
        try:
            retry_after = float(resp.headers.get("Retry-After", 0) or 0)
        except (TypeError, ValueError):
            retry_after = 0.0
        raise RateLimited(provider, retry_after=retry_after)

    if resp.status_code >= 400:
        raise ProviderError(
            f"{provider}: HTTP {resp.status_code} — {_error_text(resp)}",
            retryable=resp.status_code in RETRYABLE_CODES,
            status_code=resp.status_code,
        )
    return resp


def _error_text(resp) -> str:
    """Extract the most useful message a provider gave us, without dumping
    an entire HTML error page into a job log."""
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return (resp.text or "")[:300]

    if isinstance(payload, dict):
        for key in ("error", "detail", "message", "title"):
            val = payload.get(key)
            if isinstance(val, dict):
                val = val.get("message") or val.get("detail")
            if isinstance(val, str) and val.strip():
                return val[:300]
    return str(payload)[:300]


def get_json(url: str, *, provider: str = "", **kwargs) -> dict:
    resp = request("GET", url, provider=provider, **kwargs)
    try:
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"{provider}: response was not JSON", retryable=False) from exc


def post_json(url: str, *, provider: str = "", **kwargs) -> dict:
    resp = request("POST", url, provider=provider, **kwargs)
    if not resp.content:
        return {}
    try:
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"{provider}: response was not JSON", retryable=False) from exc


def download(url: str, *, provider: str = "", timeout: Any = DEFAULT_TIMEOUT,
             max_bytes: int = 512 * 1024 * 1024) -> tuple[bytes, str]:
    """Stream a generated asset down, refusing anything implausibly large.

    Returns (bytes, content_type).
    """
    resp = request("GET", url, provider=provider, timeout=timeout, stream=True)
    mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip()

    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=256 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ProviderError(
                f"{provider}: asset exceeded {max_bytes} byte cap", retryable=False
            )
        chunks.append(chunk)
    return b"".join(chunks), mime
