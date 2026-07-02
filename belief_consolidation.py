"""Phase 16 — bridge that feeds evidence into belief_store on a cadence.

Runs from mind_tick. Uses a persisted ISO-timestamp WATERMARK so each personal
fact is consolidated at most once (loop iterations must not inflate confidence —
reinforcement should reflect distinct sightings over days, not tick frequency).
"""
import json
import os
import threading
from typing import Any, Dict, List, Tuple

import belief_store

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_BASE_DIR, "belief_consolidation_state.json")
_EPOCH = "0000-00-00T00:00:00"

_lock = threading.RLock()


def _load_watermark() -> str:
    with _lock:
        if not os.path.exists(_STATE_PATH):
            return _EPOCH
        try:
            with open(_STATE_PATH) as f:
                return (json.load(f) or {}).get("watermark", _EPOCH)
        except Exception:
            return _EPOCH


def _save_watermark(ts: str) -> None:
    with _lock:
        try:
            tmp = _STATE_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"watermark": ts}, f)
            os.replace(tmp, _STATE_PATH)
        except Exception:
            pass


def _reset_for_test() -> None:
    with _lock:
        try:
            if os.path.exists(_STATE_PATH):
                os.remove(_STATE_PATH)
        except Exception:
            pass


def _gather_from_personal_facts(since_ts: str) -> Tuple[List[Dict[str, Any]], str]:
    """Facts newer than `since_ts` -> belief evidence. Returns (evidence, new_wm)."""
    evidence: List[Dict[str, Any]] = []
    new_wm = since_ts
    try:
        import personal_facts
        for f in personal_facts.get_all_facts():
            ts = f.get("ts", "")
            if not ts or ts <= since_ts:
                continue
            raw = (f.get("raw") or "").strip()
            if not raw:
                continue
            evidence.append({
                "subject": f.get("category", "other"),
                "statement": raw,
                "source": "personal_facts",
            })
            if ts > new_wm:
                new_wm = ts
    except Exception:
        pass
    return evidence, new_wm


def run(now: float = None) -> Dict[str, Any]:
    """Consolidate any new personal facts into beliefs, then age the store."""
    with _lock:
        wm = _load_watermark()
        evidence, new_wm = _gather_from_personal_facts(wm)
        summary = belief_store.consolidate(evidence)
        summary["processed_facts"] = len(evidence)
        summary["decayed_dropped"] = belief_store.apply_decay(now=now)
        if new_wm > wm:
            _save_watermark(new_wm)
        return summary
