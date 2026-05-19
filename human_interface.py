"""
human_interface.py — Human-in-the-Loop (HITL) approval system for Ultron-J.

For high-stakes actions (shell commands, file deletes, config changes,
self-modify patches), Ultron-J should NOT just go ahead. This module is the
gate. It maintains a pending-approval queue, lets Jeevan accept/deny via
voice or UI, and records every decision for audit.

Calling pattern from anywhere in the codebase:

    from human_interface import request_approval, wait_for_approval

    req_id = request_approval(
        kind="shell",
        summary="rm -rf /tmp/ultron_cache",
        details={"cmd": "rm -rf /tmp/ultron_cache", "reason": "low disk"},
        timeout_sec=120,
        risk_level="high",
    )
    decision = wait_for_approval(req_id, timeout=120)
    if decision == "approved":
        # do the thing
    else:
        # log and skip

The module is a tiny thread-safe queue persisted to disk so a restart doesn't
lose pending approvals (they get auto-denied with reason=restart).

Public API:
    request_approval(kind, summary, details, timeout_sec, risk_level) -> req_id
    wait_for_approval(req_id, timeout) -> "approved" | "denied" | "timeout"
    list_pending() -> list of pending requests
    decide(req_id, decision, reason) -> bool
    auto_approve_kind(kind, enabled)  -> set per-kind auto-approve (DANGEROUS)
    get_audit_log(n=50)
"""

import json
import os
import time
import uuid
import threading
import datetime
from typing import Dict, List, Optional

try:
    from config import _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))


PENDING_FILE = os.path.join(_BASE_DIR, "approval_pending.json")
AUDIT_FILE   = os.path.join(_BASE_DIR, "approval_audit.json")
SETTINGS_FILE = os.path.join(_BASE_DIR, "approval_settings.json")

DEFAULT_TIMEOUT = 120  # seconds
MAX_PENDING = 50
MAX_AUDIT = 500


# =============================================================================
# RISK LEVELS — severity hints for the UI
# =============================================================================
RISK_LEVELS = ("low", "medium", "high", "critical")


# =============================================================================
# STORAGE
# =============================================================================

_lock = threading.Lock()
_event_per_request: Dict[str, threading.Event] = {}


def _load_pending() -> Dict[str, Dict]:
    if not os.path.exists(PENDING_FILE):
        return {}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


try:
    from memory import atomic_json_write as _atomic_write
except Exception:
    def _atomic_write(filepath, data):
        with open(filepath, "w", encoding="utf-8") as _f:
            json.dump(data, _f, indent=2, ensure_ascii=False)


def _save_pending(d: Dict[str, Dict]):
    try:
        _atomic_write(PENDING_FILE, d)
    except Exception as e:
        print(f"[human_interface] save pending failed: {e}")


def _append_audit(entry: Dict):
    log = []
    if os.path.exists(AUDIT_FILE):
        try:
            with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                log = json.load(f) or []
        except Exception:
            log = []
    log.append(entry)
    try:
        _atomic_write(AUDIT_FILE, log[-MAX_AUDIT:])
    except Exception:
        pass


def get_audit_log(n: int = 50) -> List[Dict]:
    if not os.path.exists(AUDIT_FILE):
        return []
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as f:
            log = json.load(f) or []
        return log[-n:][::-1]
    except Exception:
        return []


def _load_settings() -> Dict:
    if not os.path.exists(SETTINGS_FILE):
        return {"auto_approve_kinds": []}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"auto_approve_kinds": []}


def _save_settings(s: Dict):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


# =============================================================================
# REQUEST / DECIDE
# =============================================================================

def request_approval(
    kind: str,
    summary: str,
    details: Optional[Dict] = None,
    timeout_sec: int = DEFAULT_TIMEOUT,
    risk_level: str = "medium",
) -> str:
    """Create an approval request. Returns the request id.

    Caller can then call wait_for_approval(req_id, timeout) to block until
    Jeevan decides, or list_pending() / decide() to handle it from the UI.
    """
    settings = _load_settings()
    risk_level = risk_level if risk_level in RISK_LEVELS else "medium"

    # Auto-approve check (LOW risk + kind on auto-approve list)
    if (kind in settings.get("auto_approve_kinds", [])
            and risk_level in ("low", "medium")):
        req_id = str(uuid.uuid4())[:8]
        _append_audit({
            "id":         req_id,
            "kind":       kind,
            "summary":    summary,
            "decision":   "approved",
            "reason":     "auto-approved by settings",
            "risk":       risk_level,
            "decided_at": datetime.datetime.now().isoformat(),
        })
        # We still need an event so wait_for_approval works
        ev = threading.Event()
        ev.set()
        _event_per_request[req_id] = ev
        return req_id

    req_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.now()
    entry = {
        "id":          req_id,
        "kind":        kind,
        "summary":     summary[:300],
        "details":     details or {},
        "risk_level":  risk_level,
        "created_at":  now.isoformat(),
        "expires_at":  (now + datetime.timedelta(seconds=timeout_sec)).isoformat(),
        "status":      "pending",
    }

    with _lock:
        pending = _load_pending()
        pending[req_id] = entry

        # Trim oldest if we hit the cap
        if len(pending) > MAX_PENDING:
            sorted_items = sorted(pending.items(), key=lambda x: x[1].get("created_at", ""))
            for old_id, _ in sorted_items[:len(pending) - MAX_PENDING]:
                pending.pop(old_id, None)
                _event_per_request.pop(old_id, None)

        _save_pending(pending)
        _event_per_request[req_id] = threading.Event()

    print(f"[human_interface] APPROVAL NEEDED [{risk_level}] {kind}: {summary[:100]}")
    return req_id


def wait_for_approval(req_id: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Block until decided. Returns 'approved', 'denied', or 'timeout'."""
    ev = _event_per_request.get(req_id)
    if ev is None:
        # Maybe already decided & cleaned up? Look at audit
        for entry in get_audit_log(n=200):
            if entry.get("id") == req_id:
                return entry.get("decision", "denied")
        return "denied"  # unknown

    fired = ev.wait(timeout=timeout)
    if not fired:
        # Timeout: auto-deny
        decide(req_id, "denied", reason="timeout")
        return "timeout"

    # Look up actual decision in audit
    for entry in get_audit_log(n=200):
        if entry.get("id") == req_id:
            return entry.get("decision", "denied")
    return "denied"


def decide(req_id: str, decision: str, reason: str = "") -> bool:
    """Record a decision and wake any thread waiting on this request."""
    if decision not in ("approved", "denied"):
        return False

    with _lock:
        pending = _load_pending()
        entry = pending.pop(req_id, None)
        _save_pending(pending)

    if not entry:
        return False

    audit_entry = {
        "id":         req_id,
        "kind":       entry["kind"],
        "summary":    entry["summary"],
        "decision":   decision,
        "reason":     reason or "user decision",
        "risk":       entry.get("risk_level", "medium"),
        "decided_at": datetime.datetime.now().isoformat(),
    }
    _append_audit(audit_entry)

    ev = _event_per_request.pop(req_id, None)
    if ev:
        ev.set()
    return True


def list_pending() -> List[Dict]:
    """List currently pending approval requests, ordered newest-first."""
    pending = _load_pending()
    items = list(pending.values())
    # Auto-expire timed-out items
    now = datetime.datetime.now()
    still_pending = []
    for item in items:
        try:
            expires = datetime.datetime.fromisoformat(item.get("expires_at", ""))
            if expires < now:
                # Auto-deny
                decide(item["id"], "denied", reason="expired")
                continue
        except Exception:
            pass
        still_pending.append(item)
    still_pending.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return still_pending


def auto_approve_kind(kind: str, enabled: bool):
    """DANGEROUS — set whether a given kind auto-approves on low/medium risk."""
    settings = _load_settings()
    aa = set(settings.get("auto_approve_kinds", []))
    if enabled:
        aa.add(kind)
    else:
        aa.discard(kind)
    settings["auto_approve_kinds"] = sorted(aa)
    _save_settings(settings)


def get_settings() -> Dict:
    return _load_settings()


def get_status() -> Dict:
    pending = list_pending()
    audit = get_audit_log(n=20)
    by_decision = {}
    for a in audit:
        d = a.get("decision", "?")
        by_decision[d] = by_decision.get(d, 0) + 1
    return {
        "pending_count":       len(pending),
        "pending":             [{"id": p["id"], "kind": p["kind"], "summary": p["summary"],
                                 "risk": p.get("risk_level"), "created_at": p["created_at"]}
                                for p in pending[:10]],
        "recent_decisions":    by_decision,
        "auto_approve_kinds":  _load_settings().get("auto_approve_kinds", []),
    }


# =============================================================================
# STARTUP CLEANUP — auto-deny anything left pending across a restart
# =============================================================================

def cleanup_stale_on_startup():
    """Called once at app start. Pending requests older than 5 minutes are auto-denied
    because the threads waiting for them are gone."""
    pending = _load_pending()
    if not pending:
        return
    cutoff = datetime.datetime.now() - datetime.timedelta(minutes=5)
    cleaned = 0
    for req_id, entry in list(pending.items()):
        try:
            created = datetime.datetime.fromisoformat(entry.get("created_at", ""))
            if created < cutoff:
                decide(req_id, "denied", reason="restart-cleanup")
                cleaned += 1
        except Exception:
            decide(req_id, "denied", reason="restart-cleanup-malformed")
            cleaned += 1
    if cleaned:
        print(f"[human_interface] cleaned up {cleaned} stale approval(s) from previous run")


# Auto-run cleanup on import
try:
    cleanup_stale_on_startup()
except Exception as e:
    print(f"[human_interface] startup cleanup error: {e}")


if __name__ == "__main__":
    rid = request_approval("shell", "ls -la /tmp", {"cmd": "ls -la /tmp"},
                            timeout_sec=10, risk_level="low")
    print(f"Created {rid}")
    print(json.dumps(get_status(), indent=2))
