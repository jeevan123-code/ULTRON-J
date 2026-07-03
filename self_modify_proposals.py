"""Phase 23 — self-modification autonomy WITH a human-approval gate + ledger.

Ultron rewriting its own code is the highest-risk autonomy. This layer makes it
safe: a proposed patch is STAGED (compile-checked) but NEVER auto-applied. A
human must approve() it; only then is it written (via self_modify.patch_file_direct,
which takes its own backup). Every proposal/approval/apply/rollback is recorded
in an append-only LEDGER, and any applied patch can be rolled back to its backup.

There is intentionally NO flag that makes this auto-apply — approval is always
manual. That is the safety property.
"""
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROPOSALS_PATH = os.path.join(_BASE_DIR, "self_modify_proposals.json")
_LEDGER_PATH = os.path.join(_BASE_DIR, "self_modify_ledger.json")

_lock = threading.RLock()


def _now() -> float:
    return time.time()


def _reset_for_test() -> None:
    with _lock:
        for p in (_PROPOSALS_PATH, _LEDGER_PATH):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


def _load(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f) or []
    except Exception:
        return []


def _save(path: str, data: List[Dict[str, Any]]) -> None:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def _ledger_append(entry: Dict[str, Any]) -> None:
    led = _load(_LEDGER_PATH)
    entry["ts"] = _now()
    led.append(entry)
    _save(_LEDGER_PATH, led)


def get_ledger(n: int = 50) -> List[Dict[str, Any]]:
    return _load(_LEDGER_PATH)[-n:][::-1]


# ── seams (mockable) ─────────────────────────────────────────────────────────
def _allowed_files() -> Dict[str, str]:
    try:
        import self_modify
        return dict(self_modify.ALLOWED_FILES)
    except Exception:
        return {}


def _apply(filename: str, new_code: str) -> Dict[str, Any]:
    import self_modify
    return self_modify.patch_file_direct(filename, new_code)


def _rollback(filename: str) -> Dict[str, Any]:
    import self_modify
    return self_modify.rollback(filename)


# ── proposal lifecycle ───────────────────────────────────────────────────────
def propose(filename: str, new_code: str, request: str = "",
            rationale: str = "") -> Dict[str, Any]:
    """Stage a self-modification. Validates target + syntax; does NOT apply."""
    if filename not in _allowed_files():
        return {"ok": False, "error": f"'{filename}' is not an allowed patch target"}
    if filename.endswith(".py"):
        try:
            compile(new_code, filename, "exec")
        except SyntaxError as e:
            return {"ok": False,
                    "error": f"proposed patch has a SyntaxError at line {e.lineno}: {e.msg}"}
    with _lock:
        proposals = _load(_PROPOSALS_PATH)
        entry = {
            "id": str(uuid.uuid4())[:8],
            "filename": filename,
            "new_code": new_code,
            "request": request,
            "rationale": rationale,
            "status": "pending",
            "created_at": _now(),
        }
        proposals.append(entry)
        _save(_PROPOSALS_PATH, proposals)
        _ledger_append({"event": "proposed", "id": entry["id"], "filename": filename})
    return {"ok": True, "id": entry["id"], "status": "pending"}


def list_pending() -> List[Dict[str, Any]]:
    return [p for p in _load(_PROPOSALS_PATH) if p.get("status") == "pending"]


def get(proposal_id: str) -> Optional[Dict[str, Any]]:
    return next((p for p in _load(_PROPOSALS_PATH) if p.get("id") == proposal_id), None)


def approve(proposal_id: str) -> Dict[str, Any]:
    """Human approval -> apply the staged patch. Records the outcome + backup."""
    with _lock:
        proposals = _load(_PROPOSALS_PATH)
        entry = next((p for p in proposals if p.get("id") == proposal_id), None)
        if entry is None:
            return {"ok": False, "error": "no such proposal"}
        if entry.get("status") != "pending":
            return {"ok": False, "error": f"proposal is {entry.get('status')}, not pending"}

        result = _apply(entry["filename"], entry["new_code"])
        if result.get("success"):
            entry["status"] = "applied"
            entry["applied_at"] = _now()
            entry["backup"] = result.get("backup")
            _save(_PROPOSALS_PATH, proposals)
            _ledger_append({"event": "applied", "id": proposal_id,
                            "filename": entry["filename"], "backup": result.get("backup")})
            return {"ok": True, "status": "applied", "backup": result.get("backup")}
        entry["status"] = "failed"
        _save(_PROPOSALS_PATH, proposals)
        _ledger_append({"event": "apply_failed", "id": proposal_id,
                        "error": result.get("error")})
        return {"ok": False, "error": result.get("error", "apply failed")}


def reject(proposal_id: str) -> bool:
    with _lock:
        proposals = _load(_PROPOSALS_PATH)
        entry = next((p for p in proposals if p.get("id") == proposal_id), None)
        if entry is None or entry.get("status") != "pending":
            return False
        entry["status"] = "rejected"
        _save(_PROPOSALS_PATH, proposals)
        _ledger_append({"event": "rejected", "id": proposal_id})
        return True


def rollback(proposal_id: str) -> Dict[str, Any]:
    """Roll an applied patch back to its backup."""
    with _lock:
        proposals = _load(_PROPOSALS_PATH)
        entry = next((p for p in proposals if p.get("id") == proposal_id), None)
        if entry is None or entry.get("status") != "applied":
            return {"ok": False, "error": "no applied proposal with that id"}
        result = _rollback(entry["filename"])
        ok = bool(result.get("success", result.get("ok")))
        if ok:
            entry["status"] = "rolled_back"
            _save(_PROPOSALS_PATH, proposals)
            _ledger_append({"event": "rolled_back", "id": proposal_id,
                            "filename": entry["filename"]})
            return {"ok": True, "status": "rolled_back"}
        return {"ok": False, "error": result.get("error", "rollback failed")}
