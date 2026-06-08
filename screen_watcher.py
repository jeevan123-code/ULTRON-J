"""Screen Watcher — background polling loop feeding struggle_detector.

Phase 3a stays observation-only. When struggle_detector emits a StuckEvent,
we log it to ultron_log.txt; Phase 3b will subscribe and act.

Off-switch: set environment variable `ULTRON_EYES_CLOSED=1` to suspend.
Sensitive-mode auto-pause: banking / password / secret_file screens are
classified and skip detector ingestion.
"""
import os
import re
import threading
import time
from typing import Optional

import struggle_detector
from struggle_types import (
    ScreenSnapshot,
    SensitivityKind,
)


_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ultron_log.txt")
_DEFAULT_POLL_SECONDS = 10
_running = False
_thread: Optional[threading.Thread] = None


def _get_screen_engine():
    """Indirection so tests can patch without importing the real screen engine."""
    import screen_engine
    return screen_engine


def _reset_for_test() -> None:
    global _running, _thread
    _running = False
    _thread = None


# ─────────────────────────────────────────────────────────────────────────────
# Sensitivity classification
# ─────────────────────────────────────────────────────────────────────────────

_BANKING_KEYWORDS = ("bank", "online banking", "credit card", "wire transfer", "iban")
_PASSWORD_KEYWORDS = ("password", "passcode", "••••", "•• ")
_SECRET_FILE_PATTERNS = (r"\.env\b", r"credentials\.json", r"secrets?\.json", r"id_rsa", r"\.pem\b")


def classify_sensitivity(active_window: str, screen_text: str) -> SensitivityKind:
    """Decide whether the current screen contains sensitive content.

    Order matters — most-specific first."""
    title_lc = (active_window or "").lower()
    text_lc = (screen_text or "").lower()

    for kw in _BANKING_KEYWORDS:
        if kw in title_lc or kw in text_lc:
            return SensitivityKind.BANKING
    if any(re.search(p, title_lc) for p in _SECRET_FILE_PATTERNS):
        return SensitivityKind.SECRET_FILE
    for kw in _PASSWORD_KEYWORDS:
        if kw in text_lc:
            return SensitivityKind.PASSWORD_FIELD
    return SensitivityKind.NONE


def normalize_error_signature(text: str) -> str:
    """Produce a stable lowercase signature for an error message.

    Strips whitespace, lowercases, drops quotes and single-letter identifiers
    so 'NameError: name x is not defined' and 'NameError: name y is not defined'
    map to the same signature.
    """
    if not text:
        return ""
    s = text.strip().lower()
    s = re.sub(r"['\"`]", "", s)
    s = re.sub(r"\b[a-z]\b", "", s)
    s = re.sub(r"\s+", "", s)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot + tick
# ─────────────────────────────────────────────────────────────────────────────

def take_snapshot() -> Optional[ScreenSnapshot]:
    """Pull a snapshot from screen_engine. Returns None on any failure."""
    try:
        engine = _get_screen_engine()
        result = engine.detect_errors_on_screen() or {}
    except Exception:
        return None
    has_error = bool(result.get("has_error"))
    error_text = result.get("error_text", "") or ""
    active_window = result.get("active_window", "") or ""
    sensitivity = classify_sensitivity(active_window, error_text)
    return ScreenSnapshot(
        ts=time.time(),
        active_window=active_window,
        error_text=error_text if has_error else "",
        error_signature=normalize_error_signature(error_text) if has_error else "",
        sensitivity=sensitivity,
    )


def _log_event(event) -> None:
    try:
        with open(_LOG_PATH, "a") as f:
            f.write(f"[phase3a][stuck] {event.to_dict()}\n")
    except Exception:
        pass


def _tick() -> None:
    """One observation cycle."""
    if os.environ.get("ULTRON_EYES_CLOSED", "0") == "1":
        return
    snap = take_snapshot()
    if snap is None:
        return
    event = struggle_detector.ingest(snap)
    if event is not None:
        _log_event(event)
        if os.environ.get("ULTRON_PHASE3B_ENABLED", "0") == "1":
            try:
                from proactive_offer import handle_stuck_event as _p3b_handle
                _p3b_handle(event)
            except Exception as e:
                try:
                    with open(_LOG_PATH, "a") as f:
                        f.write(f"[phase3b][offer_error] {e!r}\n")
                except Exception:
                    pass
        if os.environ.get("ULTRON_PHASE5D_ENABLED", "0") == "1":
            try:
                from struggle_counter import record_struggle as _p5d_record
                _p5d_record(ts=event.last_seen_ts)
            except Exception as e:
                try:
                    with open(_LOG_PATH, "a") as f:
                        f.write(f"[phase5d][counter_error] {e!r}\n")
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# Background runner
# ─────────────────────────────────────────────────────────────────────────────

def _loop(poll_seconds: int):
    global _running
    while _running:
        try:
            _tick()
        except Exception as e:
            try:
                with open(_LOG_PATH, "a") as f:
                    f.write(f"[phase3a][loop_error] {e!r}\n")
            except Exception:
                pass
        time.sleep(poll_seconds)


def start(poll_seconds: int = _DEFAULT_POLL_SECONDS) -> bool:
    global _running, _thread
    if _running:
        return False
    _running = True
    _thread = threading.Thread(target=_loop, args=(poll_seconds,),
                               daemon=True, name="screen_watcher")
    _thread.start()
    return True


def stop() -> bool:
    global _running, _thread
    if not _running:
        return False
    _running = False
    _thread = None
    return True


def is_running() -> bool:
    return _running
