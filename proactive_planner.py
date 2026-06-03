"""
proactive_planner.py — Pattern-driven goal generation for Ultron-J.

Existing system flow is mostly reactive: Jeevan speaks or types → Ultron answers.
This module inverts that. It periodically asks: "What would be useful RIGHT NOW
that Jeevan hasn't asked for yet?"

Signals it monitors:
  - PATTERNS          peak active hours, recurring topics (memory.get_pattern_context)
  - IDLE PROJECTS     projects with last_seen > N days (system_monitor's stale detection)
  - LESSONS           recurring pain points from memory_distiller
  - PERCEPTION        new desktop files, recent clipboard intents
  - SYSTEM HEALTH     ram/disk/battery alerts
  - TIME-OF-DAY       morning → daily plan; night → tomorrow prep
  - CALENDAR          (future: hook into calendar)

Output: "suggestions" — short, dismissable nudges stored via
system_monitor.add_proposal or exposed via the existing
pop_agent_suggestions channel. Nothing is auto-executed.

For certain high-confidence patterns (e.g. "every weekday at 9am you ask for
the day's briefing"), the planner can promote a suggestion into a
goal via decision_engine.create_goal — but only with a confidence
threshold and only after N consecutive observations.
"""

import json
import os
import re
import time
import threading
import datetime
from typing import Dict, List, Optional

try:
    from config import _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from memory import get_pattern_context, load_patterns
    _MEMORY_AVAILABLE = True
except ImportError:
    _MEMORY_AVAILABLE = False
    def get_pattern_context(): return ""
    def load_patterns(): return {}

try:
    from system_monitor import (
        get_system_health_score, get_desktop_files,
        get_heartbeat_suggestions, add_proposal,
    )
    _SYS_AVAILABLE = True
except ImportError:
    _SYS_AVAILABLE = False
    def get_system_health_score(): return 100
    def get_desktop_files(): return []
    def get_heartbeat_suggestions(): return []
    def add_proposal(**kw): return {}

try:
    from perception import get_recent_perceptions
    _PERCEPTION_AVAILABLE = True
except ImportError:
    _PERCEPTION_AVAILABLE = False
    def get_recent_perceptions(n=10): return []

try:
    from decision_engine import create_goal, get_active_goals
    _DECISION_AVAILABLE = True
except ImportError:
    _DECISION_AVAILABLE = False
    def create_goal(**kw): return {}
    def get_active_goals(): return []

try:
    from memory_distiller import get_lessons
    _DISTILLER_AVAILABLE = True
except ImportError:
    def get_lessons(n=20, category=None): return []

try:
    import model_selector as ms
except ImportError:
    ms = None

try:
    from llm_engine import call_llm_batch
except ImportError:
    def call_llm_batch(p, **kw): return ""


SUGGESTIONS_FILE = os.path.join(_BASE_DIR, "proactive_suggestions.json")
PROACTIVE_STATE  = os.path.join(_BASE_DIR, "proactive_state.json")

DEFAULT_INTERVAL_MINUTES = 30
STALE_PROJECT_DAYS = 5

# How many times we see the same proactive pattern before promoting it to a goal
PROMOTE_THRESHOLD = 3


_lock = threading.Lock()


# =============================================================================
# STORAGE
# =============================================================================

def _load_suggestions() -> List[Dict]:
    if not os.path.exists(SUGGESTIONS_FILE):
        return []
    try:
        with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_suggestions(items: List[Dict]):
    try:
        with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(items[-100:], f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[proactive] save failed: {e}")


def _load_state() -> Dict:
    if not os.path.exists(PROACTIVE_STATE):
        return {"last_run": None, "run_count": 0, "pattern_hits": {}}
    try:
        with open(PROACTIVE_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_run": None, "run_count": 0, "pattern_hits": {}}


def _save_state(s: Dict):
    try:
        with open(PROACTIVE_STATE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


# =============================================================================
# SIGNAL GATHERING
# =============================================================================

def gather_signals() -> Dict:
    """Collect everything that could trigger a proactive suggestion."""
    now = datetime.datetime.now()
    signals = {
        "timestamp":         now.isoformat(),
        "hour":              now.hour,
        "weekday":           now.strftime("%A"),
        "pattern_context":   "",
        "stale_projects":    [],
        "recent_lessons":    [],
        "desktop_new":       [],
        "perceptions":       [],
        "system_health":     100,
        "active_goal_count": 0,
        "heartbeat_hints":   [],
    }

    if _MEMORY_AVAILABLE:
        try:
            signals["pattern_context"] = get_pattern_context()
            patterns = load_patterns()
            projects = patterns.get("projects", {})
            cutoff = now - datetime.timedelta(days=STALE_PROJECT_DAYS)
            for name, meta in projects.items():
                try:
                    last_seen = datetime.datetime.fromisoformat(meta.get("last_seen", ""))
                    if last_seen < cutoff and meta.get("count", 0) >= 3:
                        signals["stale_projects"].append({
                            "name":      name,
                            "last_seen": meta["last_seen"],
                            "count":     meta["count"],
                        })
                except Exception:
                    continue
        except Exception:
            pass

    if _DISTILLER_AVAILABLE:
        try:
            signals["recent_lessons"] = get_lessons(n=8)
        except Exception:
            pass

    if _SYS_AVAILABLE:
        try:
            signals["system_health"] = get_system_health_score()
            signals["desktop_new"] = get_desktop_files()[:10]
            signals["heartbeat_hints"] = get_heartbeat_suggestions()[:5]
        except Exception:
            pass

    if _PERCEPTION_AVAILABLE:
        try:
            signals["perceptions"] = get_recent_perceptions(n=8)
        except Exception:
            pass

    if _DECISION_AVAILABLE:
        try:
            signals["active_goal_count"] = len(get_active_goals() or [])
        except Exception:
            pass

    return signals


# =============================================================================
# LLM-GENERATED SUGGESTIONS
# =============================================================================

_PROACTIVE_SYSTEM = """You are Ultron-J's proactive suggestion engine. Given signals about
Jeevan's current context (time, patterns, stale projects, lessons, system state),
you produce 0-3 SHORT, GENUINELY USEFUL suggestions Ultron could proactively offer.

Output ONLY JSON:
{
  "suggestions": [
    {
      "title":      "< 8 words, action-oriented",
      "rationale":  "one sentence: WHY this is useful RIGHT NOW",
      "action":     "what Ultron would do if accepted — be concrete",
      "category":   "briefing | resume_project | system_maintenance | organize | remind | learn",
      "confidence": "high | medium | low",
      "urgency":    "now | today | when_free"
    }
  ]
}

Rules:
- Zero suggestions is OK if nothing genuinely useful stands out.
- NO suggestions that require information we don't have (don't invent meetings).
- NO generic self-help suggestions ("take a break", "hydrate"). Unless it's
  clearly stale-project-related or connected to Jeevan's actual work.
- Prefer suggestions tied directly to a signal: stale project → "Want to resume
  <project_name>?"; many new desktop files → "Organize these <N> files?".
- Do NOT duplicate active goals.
"""


def _build_signal_prompt(signals: Dict, active_goals: List[Dict]) -> str:
    parts = [f"Current time: {signals['weekday']} {signals['hour']}:00"]

    if signals["pattern_context"]:
        parts.append(f"\nUsage patterns:\n{signals['pattern_context']}")

    if signals["stale_projects"]:
        parts.append(f"\nStale projects (last_seen > {STALE_PROJECT_DAYS} days ago, previously active):")
        for p in signals["stale_projects"][:5]:
            parts.append(f"  - {p['name']} (last: {p['last_seen'][:10]}, touched {p['count']}x)")

    if signals["recent_lessons"]:
        parts.append("\nRecent distilled lessons:")
        for l in signals["recent_lessons"][:5]:
            parts.append(f"  - [{l.get('category','')}] {l.get('text','')}")

    if signals["desktop_new"]:
        parts.append(f"\nDesktop has {len(signals['desktop_new'])} recent file(s). Examples:")
        for f in signals["desktop_new"][:4]:
            parts.append(f"  - {f if isinstance(f, str) else f.get('name', '?')}")

    if signals["perceptions"]:
        parts.append("\nRecent perception events:")
        for p in signals["perceptions"][:5]:
            if isinstance(p, dict):
                parts.append(f"  - [{p.get('kind','')}] {str(p.get('content',''))[:150]}")

    if signals["system_health"] < 80:
        parts.append(f"\n⚠️ System health score: {signals['system_health']}/100")

    if signals["heartbeat_hints"]:
        parts.append("\nSystem-level hints:")
        for h in signals["heartbeat_hints"][:5]:
            parts.append(f"  - {h}")

    if active_goals:
        parts.append(f"\nAlready-active goals ({len(active_goals)}):")
        for g in active_goals[:5]:
            parts.append(f"  - {g.get('description', g.get('title', ''))[:80]}")

    parts.append("\nProduce suggestions JSON now.")
    return "\n".join(parts)


def generate_suggestions() -> Dict:
    signals = gather_signals()

    # If there's nothing going on, skip
    has_signal = bool(
        signals["stale_projects"] or signals["recent_lessons"]
        or signals["desktop_new"] or signals["perceptions"]
        or signals["system_health"] < 80
        or signals["heartbeat_hints"]
    )
    if not has_signal:
        return {"success": True, "suggestions": [], "reason": "no notable signals"}

    active = get_active_goals() if _DECISION_AVAILABLE else []
    prompt = _build_signal_prompt(signals, active)

    if ms:
        parsed = ms.call_json("reasoner", prompt, system=_PROACTIVE_SYSTEM)
    else:
        raw = call_llm_batch(prompt, system=_PROACTIVE_SYSTEM, provider="gemini")
        parsed = _parse_json(raw)

    if not isinstance(parsed, dict):
        return {"success": False, "reason": "LLM output unparseable"}

    suggestions = parsed.get("suggestions", []) or []
    if not isinstance(suggestions, list):
        suggestions = []

    timestamp = datetime.datetime.now().isoformat()
    existing = _load_suggestions()
    state = _load_state()
    pattern_hits = state.get("pattern_hits", {})

    new_items = []
    promoted = []
    for s in suggestions[:3]:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", ""))[:80].strip()
        if not title:
            continue

        # Dedupe against recent same-title suggestions (within 24h)
        dedupe_cutoff = (datetime.datetime.now() - datetime.timedelta(hours=24)).isoformat()
        recent_same = any(
            e.get("title") == title and e.get("timestamp", "") > dedupe_cutoff
            for e in existing
        )
        if recent_same:
            # still increment the pattern hit counter — this tells us it's recurring
            pattern_hits[title] = pattern_hits.get(title, 0) + 1
            continue

        item = {
            "title":      title,
            "rationale":  str(s.get("rationale", ""))[:300],
            "action":     str(s.get("action", ""))[:500],
            "category":   str(s.get("category", "general")),
            "confidence": str(s.get("confidence", "medium")),
            "urgency":    str(s.get("urgency", "when_free")),
            "timestamp":  timestamp,
            "status":     "pending",
        }
        new_items.append(item)
        existing.append(item)
        pattern_hits[title] = pattern_hits.get(title, 0) + 1

        # Auto-promote to goal if high-confidence and seen N+ times
        if (item["confidence"] == "high"
                and pattern_hits[title] >= PROMOTE_THRESHOLD
                and _DECISION_AVAILABLE):
            try:
                g = create_goal(
                    description=f"Proactive: {title}",
                    reason=item["rationale"],
                    priority="medium",
                )
                if g:
                    promoted.append({"title": title, "goal_id": g.get("id")})
                    item["promoted_goal_id"] = g.get("id")
            except Exception as e:
                print(f"[proactive] promotion failed: {e}")

    _save_suggestions(existing)

    state["last_run"] = timestamp
    state["run_count"] = state.get("run_count", 0) + 1
    state["pattern_hits"] = pattern_hits
    _save_state(state)

    return {
        "success":    True,
        "timestamp":  timestamp,
        "generated":  len(new_items),
        "promoted":   promoted,
        "items":      new_items,
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
# PUBLIC GETTERS
# =============================================================================

def get_pending_suggestions(n: int = 10) -> List[Dict]:
    items = _load_suggestions()
    pending = [i for i in items if i.get("status") == "pending"]
    return pending[-n:][::-1]


def mark_suggestion(title: str, status: str) -> bool:
    """Mark a suggestion as 'accepted', 'dismissed', or 'done'."""
    items = _load_suggestions()
    for i in items:
        if i.get("title") == title and i.get("status") == "pending":
            i["status"] = status
            i["updated"] = datetime.datetime.now().isoformat()
            _save_suggestions(items)
            return True
    return False


def get_proactive_status() -> Dict:
    state = _load_state()
    items = _load_suggestions()
    return {
        "running":          is_running(),
        "last_run":         state.get("last_run"),
        "run_count":        state.get("run_count", 0),
        "total_items":      len(items),
        "pending_items":    sum(1 for i in items if i.get("status") == "pending"),
        "top_patterns":     sorted(
            state.get("pattern_hits", {}).items(), key=lambda x: x[1], reverse=True,
        )[:5],
    }


# =============================================================================
# LOOP
# =============================================================================

_loop_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _loop(interval_minutes: float):
    interval = max(60.0, interval_minutes * 60)
    print(f"[proactive] loop started — interval={interval_minutes}min")
    while not _stop.is_set():
        slept = 0
        while slept < interval and not _stop.is_set():
            time.sleep(min(30, interval - slept))
            slept += 30
        if _stop.is_set():
            break
        try:
            r = generate_suggestions()
            if r.get("generated"):
                print(f"[proactive] {r['generated']} new suggestion(s)")
        except Exception as e:
            print(f"[proactive] error: {e}")


def start_proactive(interval_minutes: float = DEFAULT_INTERVAL_MINUTES) -> bool:
    global _loop_thread
    # Phase 4.1 — gate through loop_supervisor / config.LOOPS
    from loop_supervisor import loop_enabled, loop_interval_s
    if not loop_enabled("proactive"):
        print("[proactive] loop disabled by config.LOOPS — not starting")
        return False
    interval_minutes = loop_interval_s("proactive", interval_minutes * 60) / 60
    if _loop_thread and _loop_thread.is_alive():
        return False
    _stop.clear()
    _loop_thread = threading.Thread(target=_loop, args=(interval_minutes,), daemon=True)
    _loop_thread.start()
    return True


def stop_proactive() -> bool:
    _stop.set()
    return True


def is_running() -> bool:
    return _loop_thread is not None and _loop_thread.is_alive()


def run_now() -> Dict:
    return generate_suggestions()


if __name__ == "__main__":
    print(json.dumps(run_now(), indent=2, default=str))
