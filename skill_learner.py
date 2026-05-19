"""
skill_learner.py — Adaptive skill acquisition for Ultron-J.

Watches completed task graphs, recent orchestration runs, and the distiller's
pattern notes for WORKFLOWS that keep happening with small variations. When it
finds one, it writes a "skill" — a parameterised template — into skills.json
that can be re-executed quickly next time without going through full planning.

Example:
  After seeing Jeevan trigger "research X then write a blog post" three times
  with different X values, skill_learner extracts the pattern:

    {
      "name":        "research_and_blog",
      "trigger":     ["research * then write", "blog about *", "write post on *"],
      "parameters":  ["topic"],
      "graph":       [
        {"kind": "research", "params": {"question": "{topic}", "depth": "standard"}},
        {"kind": "summarise", "params": {...}, "depends_on": ["s1"]},
        {"kind": "write_file", "params": {"path": "{topic}_post.md"}, "depends_on": ["s2"]}
      ],
      "uses":        3,
      "confidence":  "medium"
    }

Skills are stored in skills.json, indexed by name. Public API:
    learn_from_recent()            scan recent graphs, propose new skills
    find_matching_skill(request)   return best matching skill for a request
    apply_skill(skill_name, **kw)  render the skill's graph with params filled in
    get_skills()                   list all learned skills
    remove_skill(name)             delete a skill
"""

import json
import os
import re
import datetime
import threading
from typing import Dict, List, Optional

try:
    from config import _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from task_graph import TaskGraph
except ImportError:
    TaskGraph = None

try:
    import model_selector as ms
except ImportError:
    ms = None

try:
    from llm_engine import call_llm_batch
except ImportError:
    def call_llm_batch(p, **kw): return ""


SKILLS_FILE = os.path.join(_BASE_DIR, "skills.json")
SKILL_STATE = os.path.join(_BASE_DIR, "skill_learner_state.json")

MIN_GRAPHS_TO_LEARN = 3  # need at least N recent graphs to spot patterns
MAX_SKILLS = 50


_lock = threading.Lock()


# =============================================================================
# STORAGE
# =============================================================================

def _load_skills() -> Dict[str, Dict]:
    if not os.path.exists(SKILLS_FILE):
        return {}
    try:
        with open(SKILLS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_skills(skills: Dict[str, Dict]):
    try:
        # Trim to MAX_SKILLS (least-used first)
        if len(skills) > MAX_SKILLS:
            sorted_skills = sorted(skills.items(), key=lambda x: x[1].get("uses", 0))
            skills = dict(sorted_skills[-MAX_SKILLS:])
        with open(SKILLS_FILE, "w", encoding="utf-8") as f:
            json.dump(skills, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[skill_learner] save failed: {e}")


def _load_state() -> Dict:
    if not os.path.exists(SKILL_STATE):
        return {"last_run": None, "run_count": 0, "last_seen_graph": None}
    try:
        with open(SKILL_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_run": None, "run_count": 0, "last_seen_graph": None}


def _save_state(s: Dict):
    try:
        with open(SKILL_STATE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


# =============================================================================
# LEARNING
# =============================================================================

_LEARN_SYSTEM = """You are Ultron-J's skill-extractor. Given recent task-graph executions,
identify recurring WORKFLOWS that could be captured as reusable skills.

A skill is a parameterised template of the graph that can be re-executed with
different inputs. Example: if you see three graphs that all do
"research topic X → summarise → save to file", that's a workflow worth
capturing as the "research_and_save" skill with parameter `topic`.

Output ONLY JSON:
{
  "skills": [
    {
      "name":        "short_snake_case_identifier",
      "description": "one line of what it does",
      "trigger":     ["phrase pattern 1", "phrase pattern 2"],
      "parameters":  ["topic", "path"],
      "graph":       [
        {"id": "s1", "kind": "research", "params": {"question": "{topic}"}, "depends_on": []},
        {"id": "s2", "kind": "write_file", "params": {"path": "{path}"}, "depends_on": ["s1"]}
      ],
      "confidence":  "high | medium | low",
      "seen_in":     2
    }
  ]
}

Rules:
- Only report workflows seen AT LEAST TWICE in the input.
- Parameter names appear in params as "{name}" placeholders.
- Triggers are informal phrases ("research X and save", "look up Y then write").
- If nothing recurs, return {"skills": []}.
- Names must be snake_case, unique, under 30 chars.
"""


def learn_from_recent(max_graphs: int = 20) -> Dict:
    """Scan recent task graphs and propose new skills."""
    if TaskGraph is None:
        return {"success": False, "error": "task_graph unavailable"}

    recent = TaskGraph.list_all()[:max_graphs]
    if len(recent) < MIN_GRAPHS_TO_LEARN:
        return {
            "success": False,
            "reason":  f"need >= {MIN_GRAPHS_TO_LEARN} recent graphs (found {len(recent)})",
        }

    # Load full graphs (not just summaries)
    full = []
    for r in recent:
        g = TaskGraph.load(r["id"])
        if g and g.succeeded():  # only learn from SUCCESSFUL workflows
            full.append({
                "goal":  g.goal,
                "tasks": [
                    {"kind": t["kind"], "depends_on": t["depends_on"],
                     "params": {k: v for k, v in t["params"].items() if k != "_deps"}}
                    for t in g.tasks.values()
                ],
            })

    if len(full) < MIN_GRAPHS_TO_LEARN:
        return {
            "success": False,
            "reason":  f"need >= {MIN_GRAPHS_TO_LEARN} succeeded graphs (found {len(full)})",
        }

    prompt = "Recent successful task graphs:\n\n" + json.dumps(full[:15], indent=2)[:8000] \
             + "\n\nExtract recurring workflows as skills."

    if ms:
        parsed = ms.call_json("reasoner", prompt, system=_LEARN_SYSTEM)
    else:
        raw = call_llm_batch(prompt, system=_LEARN_SYSTEM, provider="gemini")
        parsed = _parse_json(raw)

    if not isinstance(parsed, dict):
        return {"success": False, "reason": "LLM output unparseable"}

    proposals = parsed.get("skills", []) or []
    if not isinstance(proposals, list):
        proposals = []

    with _lock:
        skills = _load_skills()
        added = 0
        updated = 0
        for p in proposals[:10]:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "")).strip().lower()
            name = re.sub(r"[^a-z0-9_]", "_", name)[:30]
            if not name or len(name) < 3:
                continue
            graph = p.get("graph", [])
            if not isinstance(graph, list) or len(graph) == 0:
                continue

            record = {
                "name":        name,
                "description": str(p.get("description", ""))[:300],
                "trigger":     [str(t)[:100] for t in (p.get("trigger") or [])][:5],
                "parameters":  [str(x)[:30] for x in (p.get("parameters") or [])][:8],
                "graph":       graph,
                "confidence":  str(p.get("confidence", "medium")),
                "seen_in":     int(p.get("seen_in", 2)),
                "created_at":  datetime.datetime.now().isoformat(),
                "uses":        0,
            }

            if name in skills:
                # Update existing: keep uses count, update rest
                record["uses"] = skills[name].get("uses", 0)
                record["created_at"] = skills[name].get("created_at", record["created_at"])
                skills[name] = record
                updated += 1
            else:
                skills[name] = record
                added += 1

        _save_skills(skills)

    state = _load_state()
    state["last_run"] = datetime.datetime.now().isoformat()
    state["run_count"] = state.get("run_count", 0) + 1
    _save_state(state)

    return {
        "success":  True,
        "added":    added,
        "updated":  updated,
        "total":    len(_load_skills()),
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
# SKILL MATCHING
# =============================================================================

def find_matching_skill(request: str) -> Optional[Dict]:
    """Return the best-matching skill for a user request, or None."""
    req = request.lower().strip()
    if not req:
        return None

    skills = _load_skills()
    best = None
    best_score = 0
    for name, skill in skills.items():
        triggers = skill.get("trigger", [])
        for t in triggers:
            tl = t.lower()
            # Simple substring / word-overlap scoring
            # Handle "*" as wildcard
            pattern = re.escape(tl).replace(r"\*", r".+")
            if re.search(pattern, req):
                score = len(tl)  # prefer longer matches
                if score > best_score:
                    best_score = score
                    best = skill
    return best


def apply_skill(skill_name: str, **params) -> Optional[List[Dict]]:
    """Render a skill's graph by substituting {param} placeholders.

    Returns a list of step dicts ready to feed to task_graph.graph_from_plan,
    or None if the skill doesn't exist or required params are missing.
    """
    skills = _load_skills()
    skill = skills.get(skill_name)
    if not skill:
        return None

    required = set(skill.get("parameters", []))
    missing = required - set(params.keys())
    if missing:
        print(f"[skill_learner] missing params for {skill_name}: {missing}")
        return None

    # Deep-render the graph template
    def _render(obj):
        if isinstance(obj, str):
            for k, v in params.items():
                obj = obj.replace("{" + k + "}", str(v))
            return obj
        if isinstance(obj, list):
            return [_render(x) for x in obj]
        if isinstance(obj, dict):
            return {k: _render(v) for k, v in obj.items()}
        return obj

    rendered = _render(skill["graph"])

    # Record usage
    skill["uses"] = skill.get("uses", 0) + 1
    skill["last_used"] = datetime.datetime.now().isoformat()
    skills[skill_name] = skill
    _save_skills(skills)

    return rendered


def get_skills() -> List[Dict]:
    """List all skills sorted by uses (most-used first)."""
    skills = _load_skills()
    return sorted(skills.values(), key=lambda s: s.get("uses", 0), reverse=True)


def remove_skill(name: str) -> bool:
    with _lock:
        skills = _load_skills()
        if name in skills:
            del skills[name]
            _save_skills(skills)
            return True
    return False


def get_skill_status() -> Dict:
    state = _load_state()
    skills = _load_skills()
    total_uses = sum(s.get("uses", 0) for s in skills.values())
    return {
        "total_skills": len(skills),
        "total_uses":   total_uses,
        "last_run":     state.get("last_run"),
        "run_count":    state.get("run_count", 0),
        "running":      _loop_thread is not None and _loop_thread.is_alive(),
        "interval_hours": _loop_interval_hours,
        "top_skills":   [{"name": s["name"], "uses": s.get("uses", 0)}
                         for s in get_skills()[:5]],
    }


# =============================================================================
# BACKGROUND LOOP — periodic auto-learn
# =============================================================================
# Mirrors memory_distiller's pattern: a daemon thread sleeps in 30s chunks so
# stop_skill_learner() returns promptly, runs learn_from_recent() on each
# wake, and prints a one-line summary. Wired into ultimate_routes.start_-
# ultimate_loops() so skill_learner runs on Ultron's boot like distiller /
# evolution / proactive / predictive.

import time as _time

DEFAULT_INTERVAL_HOURS = 6.0

_loop_thread: Optional[threading.Thread] = None
_loop_stop_event = threading.Event()
_loop_interval_hours: float = DEFAULT_INTERVAL_HOURS


def _skill_loop(interval_hours: float):
    interval_sec = max(60.0, interval_hours * 3600)
    print(f"[skill_learner] loop started — interval={interval_hours}h")
    while not _loop_stop_event.is_set():
        slept = 0
        while slept < interval_sec and not _loop_stop_event.is_set():
            _time.sleep(min(30, interval_sec - slept))
            slept += 30
        if _loop_stop_event.is_set():
            break
        try:
            r = learn_from_recent()
            print(f"[skill_learner] pass complete: {r}")
        except Exception as e:
            print(f"[skill_learner] loop error: {e}")


def start_skill_learner(interval_hours: float = DEFAULT_INTERVAL_HOURS) -> bool:
    """Start the auto-learn daemon. Returns True on first start, False if
    already running. Idempotent."""
    global _loop_thread, _loop_interval_hours
    if _loop_thread and _loop_thread.is_alive():
        return False
    _loop_stop_event.clear()
    _loop_interval_hours = interval_hours
    _loop_thread = threading.Thread(
        target=_skill_loop, args=(interval_hours,), daemon=True,
    )
    _loop_thread.start()
    return True


def stop_skill_learner() -> bool:
    _loop_stop_event.set()
    return True


def is_running() -> bool:
    return _loop_thread is not None and _loop_thread.is_alive()


def run_now() -> Dict:
    """Trigger an immediate skill-learning pass (blocking)."""
    return learn_from_recent()


if __name__ == "__main__":
    import sys
    if "--learn" in sys.argv:
        print(json.dumps(learn_from_recent(), indent=2))
    else:
        print(json.dumps(get_skill_status(), indent=2))
