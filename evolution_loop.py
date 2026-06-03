"""
evolution_loop.py — Meta-learning layer for Ultron-J.

Reads the accumulated output of memory_distiller, reflection, and
self_modify logs, then proposes concrete system-level improvements:

  1. SYSTEM PROMPT EVOLUTION
     — Tracks which phrases in the intelligence_core system prompts correlate
       with good vs bad outcomes (using ratings from reflection_log and
       self_modify success rates).
     — Proposes replacement lines when a pattern consistently underperforms.

  2. CONFIG TUNING
     — Observes retry counts, timeouts, temperature, provider health.
     — Proposes config.py tweaks with rationale.

  3. ROUTE PROMOTION
     — Notices frequently-hit ad-hoc workflows and suggests wrapping them
       as first-class routes / skills.

  4. FAILURE CLUSTERING
     — Groups recent failures by type and proposes preventative changes.

Every evolution is written as a *proposal* in proposals.json — the
existing mechanism (system_monitor.add_proposal) Jeevan already uses.
Nothing is auto-applied. tweak_engine.py handles the safe-apply path for
proposals the user accepts.

Key principle: evolution_loop does not MODIFY code directly. It writes
proposals. The human (or an explicit /evolve/apply call) triggers the
actual change — which goes through self_modify + visual_verify.
"""

import json
import os
import re
import time
import threading
import datetime
from typing import Dict, List, Optional

try:
    from config import (
        _BASE_DIR, REFLECTION_FILE, SELF_IMPROVE_FILE,
    )
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    REFLECTION_FILE   = os.path.join(_BASE_DIR, "reflection_log.json")
    SELF_IMPROVE_FILE = os.path.join(_BASE_DIR, "self_improvements.json")

try:
    from system_monitor import add_proposal
except ImportError:
    def add_proposal(title, description, code_snippet="", target_file="", source=""):
        return {"success": False, "error": "system_monitor not available"}

try:
    from memory_distiller import _load_lessons
except ImportError:
    def _load_lessons(): return []

try:
    import model_selector as ms
except ImportError:
    ms = None

try:
    from llm_engine import call_llm_batch
except ImportError:
    def call_llm_batch(p, **kw): return ""

try:
    from memory import atomic_json_write
except ImportError:
    def atomic_json_write(fp, d):
        with open(fp, "w", encoding="utf-8") as _f:
            json.dump(d, _f, indent=2, ensure_ascii=False)


EVOLUTION_LOG_FILE = os.path.join(_BASE_DIR, "evolution_log.json")
EVOLUTION_STATE    = os.path.join(_BASE_DIR, "evolution_state.json")

DEFAULT_INTERVAL_HOURS = 12  # run less often than distiller
MIN_LESSONS_TO_EVOLVE = 8    # don't try to evolve if there's no data


# =============================================================================
# LOG HELPERS
# =============================================================================

_log_lock = threading.Lock()


def _load_log() -> List[Dict]:
    if not os.path.exists(EVOLUTION_LOG_FILE):
        return []
    try:
        with open(EVOLUTION_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _append_log(entry: Dict):
    with _log_lock:
        log = _load_log()
        log.append(entry)
        try:
            atomic_json_write(EVOLUTION_LOG_FILE, log[-200:])
        except Exception as e:
            print(f"[evolution] log write failed: {e}")


def _load_state() -> Dict:
    if not os.path.exists(EVOLUTION_STATE):
        return {"last_run": None, "run_count": 0}
    try:
        with open(EVOLUTION_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_run": None, "run_count": 0}


def _save_state(s: Dict):
    try:
        atomic_json_write(EVOLUTION_STATE, s)
    except Exception:
        pass


# =============================================================================
# ANALYSIS
# =============================================================================

def analyse_failures(lookback: int = 30) -> Dict:
    """Cluster recent failures by kind so the LLM can see them grouped."""
    failures = {
        "self_modify":  [],
        "reflection":   [],
        "goal_exec":    [],
    }

    # Self-modify failures
    try:
        if os.path.exists(SELF_IMPROVE_FILE):
            with open(SELF_IMPROVE_FILE, "r", encoding="utf-8") as f:
                mods = json.load(f) or []
            for m in mods[-lookback:]:
                if isinstance(m, dict) and not m.get("success", True):
                    failures["self_modify"].append({
                        "desc":   m.get("description") or m.get("request", ""),
                        "target": m.get("target", ""),
                        "error":  m.get("error", ""),
                    })
    except Exception:
        pass

    # Reflection-flagged issues
    try:
        if os.path.exists(REFLECTION_FILE):
            with open(REFLECTION_FILE, "r", encoding="utf-8") as f:
                refs = json.load(f) or []
            for r in refs[-lookback:]:
                if isinstance(r, dict) and r.get("kind") in ("failure", "concern", "skill_gap"):
                    failures["reflection"].append({
                        "kind":    r.get("kind"),
                        "content": str(r.get("content", ""))[:300],
                    })
    except Exception:
        pass

    # Goal execution failures
    try:
        from decision_engine import get_execution_log
        log = get_execution_log(n=lookback)
        for e in log:
            if isinstance(e, dict) and not e.get("success"):
                failures["goal_exec"].append({
                    "action": e.get("action", ""),
                    "result": str(e.get("result", ""))[:200],
                })
    except Exception:
        pass

    counts = {k: len(v) for k, v in failures.items()}
    return {"counts": counts, "failures": failures}


def collect_lesson_categories() -> Dict[str, List[Dict]]:
    """Group distilled lessons by category for easier inspection."""
    lessons = _load_lessons()
    by_cat: Dict[str, List[Dict]] = {}
    for l in lessons[-100:]:
        cat = l.get("category", "general")
        by_cat.setdefault(cat, []).append(l)
    return by_cat


# =============================================================================
# PROPOSAL GENERATION
# =============================================================================

_EVOLVE_SYSTEM = """You are Ultron-J's self-improvement engine. You read distilled lessons,
reflection notes, and failure patterns, and produce CONCRETE, ACTIONABLE proposals
to improve the system.

Output ONLY JSON:
{
  "proposals": [
    {
      "kind":       "system_prompt | config_tweak | new_route | routing_rule | skill_gap_fix",
      "title":      "short, < 8 words",
      "reason":     "why this change (cite specific lessons/failures)",
      "target":     "file/section this affects (e.g. 'intelligence_core.py', 'config.py MAX_RETRY_ATTEMPTS')",
      "change":     "exactly what to change — be specific, reproducible",
      "confidence": "high | medium | low"
    }
  ]
}

Rules:
- At most 5 proposals per pass. Quality over quantity.
- Each proposal must cite at least one concrete lesson or failure.
- No proposals about "be better" or "add more features" — must be specific.
- For system_prompt changes: quote the current line if you can infer it, and
  give the replacement.
- For config_tweak: give the exact variable name and new value.
- If there's not enough signal, return {"proposals": []}.
"""


def propose_evolutions() -> Dict:
    """Analyse logs and produce a set of system-improvement proposals."""
    lessons = _load_lessons()
    if len(lessons) < MIN_LESSONS_TO_EVOLVE:
        return {"success": False, "reason": f"only {len(lessons)} lessons so far (need >= {MIN_LESSONS_TO_EVOLVE})"}

    failure_report = analyse_failures()
    by_category = collect_lesson_categories()

    # Build LLM input
    parts = []
    parts.append("=== Lessons by Category ===")
    for cat, items in by_category.items():
        parts.append(f"\n-- {cat} --")
        for l in items[-15:]:
            parts.append(f"  • {l.get('text','')}")
            if l.get("evidence"):
                parts.append(f"    evidence: {l['evidence'][:200]}")

    parts.append("\n=== Recent Failure Counts ===")
    for k, v in failure_report["counts"].items():
        parts.append(f"  {k}: {v}")

    if failure_report["failures"]["self_modify"]:
        parts.append("\n=== Recent Self-Modify Failures ===")
        for f in failure_report["failures"]["self_modify"][-5:]:
            parts.append(f"  - target={f['target']}: {f['error'][:200]}")

    if failure_report["failures"]["reflection"]:
        parts.append("\n=== Reflection Concerns ===")
        for f in failure_report["failures"]["reflection"][-5:]:
            parts.append(f"  - [{f['kind']}] {f['content'][:200]}")

    parts.append("\nProduce JSON proposals now.")
    prompt = "\n".join(parts)

    if ms:
        parsed = ms.call_json("reasoner", prompt, system=_EVOLVE_SYSTEM)
    else:
        raw = call_llm_batch(prompt, system=_EVOLVE_SYSTEM, provider="gemini")
        parsed = _parse_json(raw)

    if not isinstance(parsed, dict):
        return {"success": False, "reason": "LLM output unparseable"}

    proposals = parsed.get("proposals", []) or []
    if not isinstance(proposals, list):
        proposals = []

    # Write each proposal into the existing system_monitor proposals store
    # so Jeevan sees them in his existing /suggestions endpoint.
    written_ids = []
    for p in proposals[:5]:
        if not isinstance(p, dict):
            continue
        title = str(p.get("title", "Evolution"))[:80]
        reason = str(p.get("reason", ""))[:500]
        target = str(p.get("target", ""))[:200]
        change = str(p.get("change", ""))[:2000]
        kind = str(p.get("kind", "unknown"))

        description = f"[{kind}] {reason}\n\nTarget: {target}\n\nProposed change:\n{change}"

        try:
            r = add_proposal(
                title=f"🧬 {title}",
                description=description,
                code_snippet="",
                target_file=target.split()[0] if target else "",
                source="evolution_loop",
            )
            if r and r.get("id") is not None:
                written_ids.append(r["id"])
        except Exception as e:
            print(f"[evolution] add_proposal failed: {e}")

    # Append full log entry
    entry = {
        "timestamp":       datetime.datetime.now().isoformat(),
        "lessons_seen":    len(lessons),
        "failures_seen":   failure_report["counts"],
        "proposals":       proposals,
        "proposal_ids":    written_ids,
    }
    _append_log(entry)

    state = _load_state()
    state["last_run"] = entry["timestamp"]
    state["run_count"] = state.get("run_count", 0) + 1
    _save_state(state)

    return {
        "success":         True,
        "proposal_count":  len(proposals),
        "written":         len(written_ids),
        "proposals":       proposals,
    }


def _parse_json(raw: str) -> Optional[Dict]:
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"(\{.*\})", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
    return None


# =============================================================================
# BACKGROUND LOOP
# =============================================================================

_loop_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _loop(interval_hours: float):
    interval = max(300.0, interval_hours * 3600)
    print(f"[evolution] loop started — interval={interval_hours}h")
    while not _stop_event.is_set():
        slept = 0
        while slept < interval and not _stop_event.is_set():
            time.sleep(min(60, interval - slept))
            slept += 60
        if _stop_event.is_set():
            break
        try:
            r = propose_evolutions()
            print(f"[evolution] pass: {r.get('proposal_count', 0)} proposals")
        except Exception as e:
            print(f"[evolution] error: {e}")


def start_evolution(interval_hours: float = DEFAULT_INTERVAL_HOURS) -> bool:
    global _loop_thread
    # Phase 4.1 — gate through loop_supervisor / config.LOOPS
    from loop_supervisor import loop_enabled, loop_interval_s
    if not loop_enabled("evolution"):
        print("[evolution] loop disabled by config.LOOPS — not starting")
        return False
    interval_hours = loop_interval_s("evolution", interval_hours * 3600) / 3600
    if _loop_thread and _loop_thread.is_alive():
        return False
    _stop_event.clear()
    _loop_thread = threading.Thread(target=_loop, args=(interval_hours,), daemon=True)
    _loop_thread.start()
    return True


def stop_evolution() -> bool:
    _stop_event.set()
    return True


def is_running() -> bool:
    return _loop_thread is not None and _loop_thread.is_alive()


def get_evolution_status() -> Dict:
    state = _load_state()
    log = _load_log()
    return {
        "running":         is_running(),
        "last_run":        state.get("last_run"),
        "run_count":       state.get("run_count", 0),
        "log_entries":     len(log),
        "last_proposals":  log[-1]["proposals"] if log else [],
    }


def run_now() -> Dict:
    return propose_evolutions()


if __name__ == "__main__":
    print(json.dumps(run_now(), indent=2))
