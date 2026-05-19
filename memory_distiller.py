"""
memory_distiller.py — The OpenClaw-style "dreaming" layer for Ultron-J.

Every N hours (default 6), Ultron-J reads its recent logs — conversations,
reflections, execution trails, self-modify log — and distills them into:

  1. "Lessons learned"   — what worked / what didn't → added to concepts.json
                           and stored in vector_store (kind="lesson")
  2. "Knowledge updates" — new facts about Jeevan inferred from chat
  3. "Pattern notes"     — recurring workflows worth optimising for
  4. "Skill gaps"        — things Ultron struggled to do

The output files are designed to be picked up by:
  - system_prompts_manager / intelligence_core  → injects lessons into prompts
  - skill_learner                               → acts on skill gaps
  - evolution_loop                              → refines prompts & configs
  - concepts.py (reload_concepts)                → makes new concepts queryable

Runs as a background thread launched by start_distiller().
Also exposes run_now() for immediate manual triggering from the UI / voice.

Key design principle: NEVER discard raw logs — distillation is additive.
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
        _BASE_DIR, CONCEPTS_FILE, MEMORY_FILE,
        SELF_IMPROVE_FILE, REFLECTION_FILE,
    )
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CONCEPTS_FILE      = os.path.join(_BASE_DIR, "concepts.json")
    MEMORY_FILE        = os.path.join(_BASE_DIR, "memory.json")
    SELF_IMPROVE_FILE  = os.path.join(_BASE_DIR, "self_improvements.json")
    REFLECTION_FILE    = os.path.join(_BASE_DIR, "reflection_log.json")

try:
    import model_selector as ms
except ImportError:
    ms = None

try:
    from llm_engine import call_llm_batch
except ImportError:
    def call_llm_batch(p, **kw): return ""

try:
    import vector_store
    _VSTORE_AVAILABLE = True
except ImportError:
    _VSTORE_AVAILABLE = False

try:
    from concepts import reload_concepts
except ImportError:
    def reload_concepts(): pass

try:
    from memory import atomic_json_write
except ImportError:
    def atomic_json_write(fp, d):
        with open(fp, "w", encoding="utf-8") as _f:
            json.dump(d, _f, indent=2, ensure_ascii=False)


# =============================================================================
# FILES
# =============================================================================
LESSONS_FILE  = os.path.join(_BASE_DIR, "lessons_learned.json")
DISTILL_STATE = os.path.join(_BASE_DIR, "distiller_state.json")

DEFAULT_INTERVAL_HOURS = 6
MIN_CONVERSATIONS_TO_DISTILL = 20
MAX_LESSONS = 200


# =============================================================================
# STATE
# =============================================================================

_state_lock = threading.Lock()


def _load_state() -> Dict:
    if not os.path.exists(DISTILL_STATE):
        return {"last_run": None, "run_count": 0, "running": False}
    try:
        with open(DISTILL_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_run": None, "run_count": 0, "running": False}


def _save_state(state: Dict):
    with _state_lock:
        try:
            atomic_json_write(DISTILL_STATE, state)
        except Exception as e:
            print(f"[distiller] save state failed: {e}")


def _load_lessons() -> List[Dict]:
    if not os.path.exists(LESSONS_FILE):
        return []
    try:
        with open(LESSONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_lessons(lessons: List[Dict]):
    try:
        atomic_json_write(LESSONS_FILE, lessons[-MAX_LESSONS:])
    except Exception as e:
        print(f"[distiller] save lessons failed: {e}")


# =============================================================================
# SOURCE COLLECTION
# =============================================================================

def _gather_source_material() -> Dict:
    """Gather raw material from logs for distillation."""
    material = {
        "conversations":   [],
        "reflections":     [],
        "self_modifies":   [],
        "execution_log":   [],
    }

    # Conversations from memory.json
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            convs = data.get("conversations", [])[-80:]  # last 80 turns
            material["conversations"] = convs
    except Exception:
        pass

    # Reflections
    try:
        if os.path.exists(REFLECTION_FILE):
            with open(REFLECTION_FILE, "r", encoding="utf-8") as f:
                refs = json.load(f)
            material["reflections"] = refs[-20:] if isinstance(refs, list) else []
    except Exception:
        pass

    # Self-modify history
    try:
        if os.path.exists(SELF_IMPROVE_FILE):
            with open(SELF_IMPROVE_FILE, "r", encoding="utf-8") as f:
                mods = json.load(f)
            material["self_modifies"] = mods[-15:] if isinstance(mods, list) else []
    except Exception:
        pass

    # Execution log (decision_engine)
    try:
        from decision_engine import get_execution_log
        material["execution_log"] = get_execution_log(n=30) or []
    except Exception:
        pass

    return material


# =============================================================================
# DISTILLATION PROMPTS
# =============================================================================

_LESSONS_SYSTEM = """You are Ultron-J's nightly reflection process. You read raw activity logs and
distill them into short, specific lessons Ultron-J can use going forward.

Output ONLY JSON:
{
  "lessons": [
    {
      "category": "what_worked | what_failed | jeevan_preference | skill_gap | workflow_pattern",
      "text":     "one-sentence, concrete lesson",
      "evidence": "brief quote / summary from the log that supports this"
    }
  ],
  "new_concepts": [
    {"key": "short_lowercase_term", "description": "1-2 sentence concept explanation"}
  ],
  "pattern_notes": [
    "one-line pattern observation"
  ]
}

Rules:
- 3-10 lessons total is the sweet spot. Fewer is better than padding.
- Lessons must be SPECIFIC and ACTIONABLE, not generic.
  BAD:  "be helpful"
  GOOD: "When Jeevan asks for code reviews, he wants specific line-number feedback, not praise"
- new_concepts should be terms that came up in conversation that aren't yet in Ultron's knowledge base.
- pattern_notes capture recurring workflows (e.g. "Jeevan tests locally before deploying, always asks for restart commands last").
- Do NOT invent things not in the logs. If logs are too thin, return empty arrays.
"""


def _build_distill_prompt(material: Dict) -> str:
    parts = ["Distill lessons from the following Ultron-J activity logs.\n"]

    convs = material["conversations"]
    if convs:
        parts.append("=== Recent Conversations (role: message) ===")
        for c in convs[-60:]:
            role = c.get("role", "")
            msg = (c.get("message") or "")[:300]
            parts.append(f"{role}: {msg}")
        parts.append("")

    refs = material["reflections"]
    if refs:
        parts.append("=== Recent Reflections ===")
        for r in refs[-10:]:
            if isinstance(r, dict):
                parts.append(f"- [{r.get('kind','?')}] {str(r.get('content',''))[:300]}")
        parts.append("")

    mods = material["self_modifies"]
    if mods:
        parts.append("=== Recent Self-Modify Events ===")
        for m in mods[-10:]:
            if isinstance(m, dict):
                desc = m.get("description") or m.get("request") or m.get("target", "")
                parts.append(f"- {str(desc)[:200]}  success={m.get('success','?')}")
        parts.append("")

    execlog = material["execution_log"]
    if execlog:
        parts.append("=== Recent Goal Execution Steps ===")
        for e in execlog[-15:]:
            if isinstance(e, dict):
                parts.append(f"- {e.get('action','?')}: success={e.get('success','?')} — {str(e.get('result',''))[:150]}")
        parts.append("")

    parts.append("\nProduce the JSON now.")
    return "\n".join(parts)


# =============================================================================
# MAIN DISTILLATION
# =============================================================================

def distill() -> Dict:
    """Run one distillation pass. Returns a summary."""
    material = _gather_source_material()

    n_conv = len(material["conversations"])
    if n_conv < MIN_CONVERSATIONS_TO_DISTILL:
        return {
            "success":       False,
            "reason":        f"not enough conversations ({n_conv} < {MIN_CONVERSATIONS_TO_DISTILL})",
            "conversations": n_conv,
        }

    prompt = _build_distill_prompt(material)

    # Use the reasoner kind — we want quality over speed here
    if ms:
        parsed = ms.call_json("reasoner", prompt, system=_LESSONS_SYSTEM)
    else:
        raw = call_llm_batch(prompt, system=_LESSONS_SYSTEM, provider="gemini")
        parsed = _parse_json(raw)

    if not isinstance(parsed, dict):
        return {"success": False, "reason": "distillation produced unparseable output"}

    lessons_out       = parsed.get("lessons", []) or []
    new_concepts_out  = parsed.get("new_concepts", []) or []
    pattern_notes_out = parsed.get("pattern_notes", []) or []

    timestamp = datetime.datetime.now().isoformat()

    # ── Write lessons ──
    existing = _load_lessons()
    added_lesson_count = 0
    for lesson in lessons_out:
        if not isinstance(lesson, dict):
            continue
        text = str(lesson.get("text", "")).strip()
        if not text or len(text) < 10:
            continue
        # Simple dedupe: skip if the same text already exists in recent lessons
        if any(l.get("text") == text for l in existing[-50:]):
            continue
        record = {
            "text":      text,
            "category":  str(lesson.get("category", "general"))[:40],
            "evidence":  str(lesson.get("evidence", ""))[:500],
            "timestamp": timestamp,
        }
        existing.append(record)
        added_lesson_count += 1

        # Also store in vector_store for retrieval during thinking
        if _VSTORE_AVAILABLE:
            try:
                vector_store.remember_lesson(text, source="distiller")
            except Exception:
                pass

    _save_lessons(existing)

    # ── Write new concepts ──
    added_concept_count = _add_concepts_to_file(new_concepts_out)
    if added_concept_count > 0:
        try:
            reload_concepts()
        except Exception:
            pass

    # ── Update state ──
    state = _load_state()
    state["last_run"] = timestamp
    state["run_count"] = state.get("run_count", 0) + 1
    state["running"] = False
    state["last_summary"] = {
        "lessons_added":     added_lesson_count,
        "concepts_added":    added_concept_count,
        "patterns_noted":    len(pattern_notes_out),
        "conversations_in":  n_conv,
    }
    _save_state(state)

    return {
        "success":          True,
        "timestamp":        timestamp,
        "lessons_added":    added_lesson_count,
        "concepts_added":   added_concept_count,
        "pattern_notes":    pattern_notes_out,
        "conversations":   n_conv,
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


def _add_concepts_to_file(new_concepts: List[Dict]) -> int:
    """Add only genuinely new concepts to concepts.json."""
    if not new_concepts:
        return 0
    try:
        if os.path.exists(CONCEPTS_FILE):
            with open(CONCEPTS_FILE, "r", encoding="utf-8") as f:
                current = json.load(f) or {}
        else:
            current = {}
    except Exception:
        current = {}

    added = 0
    for c in new_concepts:
        if not isinstance(c, dict):
            continue
        key = str(c.get("key", "")).strip().lower()
        desc = str(c.get("description", "")).strip()
        if not key or not desc or len(key) < 2 or len(key) > 60:
            continue
        if key in current:  # don't clobber existing definitions
            continue
        # Basic sanity: key should look like a term, not a sentence
        if len(key.split()) > 6:
            continue
        current[key] = desc
        added += 1

    if added > 0:
        try:
            atomic_json_write(CONCEPTS_FILE, current)
        except Exception as e:
            print(f"[distiller] save concepts failed: {e}")
            return 0
    return added


# =============================================================================
# BACKGROUND LOOP
# =============================================================================

_loop_thread: Optional[threading.Thread] = None
_loop_stop_event = threading.Event()


def _distill_loop(interval_hours: float):
    interval_sec = max(60.0, interval_hours * 3600)
    print(f"[distiller] loop started — interval={interval_hours}h")
    while not _loop_stop_event.is_set():
        # Sleep in short chunks so we respond to stop
        total_slept = 0
        while total_slept < interval_sec and not _loop_stop_event.is_set():
            time.sleep(min(30, interval_sec - total_slept))
            total_slept += 30
        if _loop_stop_event.is_set():
            break
        try:
            state = _load_state()
            if state.get("running"):
                continue  # another run in progress
            state["running"] = True
            _save_state(state)
            r = distill()
            print(f"[distiller] pass complete: {r}")
        except Exception as e:
            print(f"[distiller] loop error: {e}")
            s = _load_state()
            s["running"] = False
            _save_state(s)


def start_distiller(interval_hours: float = DEFAULT_INTERVAL_HOURS) -> bool:
    global _loop_thread
    if _loop_thread and _loop_thread.is_alive():
        return False
    _loop_stop_event.clear()
    _loop_thread = threading.Thread(
        target=_distill_loop, args=(interval_hours,), daemon=True,
    )
    _loop_thread.start()
    return True


def stop_distiller() -> bool:
    _loop_stop_event.set()
    return True


def is_running() -> bool:
    return _loop_thread is not None and _loop_thread.is_alive()


def run_now() -> Dict:
    """Trigger an immediate distillation pass (blocking)."""
    state = _load_state()
    state["running"] = True
    _save_state(state)
    try:
        return distill()
    finally:
        s = _load_state()
        s["running"] = False
        _save_state(s)


def get_lessons(n: int = 20, category: Optional[str] = None) -> List[Dict]:
    lessons = _load_lessons()
    if category:
        lessons = [l for l in lessons if l.get("category") == category]
    return lessons[-n:][::-1]  # newest first


def get_distiller_status() -> Dict:
    state = _load_state()
    lessons = _load_lessons()
    return {
        "running":        is_running(),
        "last_run":       state.get("last_run"),
        "run_count":      state.get("run_count", 0),
        "total_lessons":  len(lessons),
        "last_summary":   state.get("last_summary", {}),
    }


if __name__ == "__main__":
    import sys
    if "--run" in sys.argv:
        print(json.dumps(run_now(), indent=2))
    else:
        print(json.dumps(get_distiller_status(), indent=2))
