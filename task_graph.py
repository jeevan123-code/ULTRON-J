"""
task_graph.py — Directed-Acyclic-Graph task structure.

Used by brain_orchestrator.py to decompose complex requests into a graph
of sub-tasks where edges mean "B depends on A's output". Unlike the linear
plans in decision_engine.py, this lets Ultron-J execute independent branches
in parallel and always respect real dependencies.

A TaskGraph persists itself to JSON so that if Ultron-J crashes mid-execution,
it can resume — that's the OpenClaw "persistent state registry" pattern.

Usage:
    g = TaskGraph()
    a = g.add("search", {"query": "claude 4 features"})
    b = g.add("summarise", {}, depends_on=[a])
    c = g.add("write_file", {"path": "out.md"}, depends_on=[b])
    while not g.done():
        ready = g.ready_tasks()
        for t in ready:
            result = execute(t)           # caller runs the task
            g.complete(t["id"], result)   # or g.fail(t["id"], error)
"""

import json
import os
import uuid
import datetime
import threading
from typing import Dict, List, Optional, Any

try:
    from config import _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TASK_GRAPHS_DIR = os.path.join(_BASE_DIR, "task_graphs")
os.makedirs(TASK_GRAPHS_DIR, exist_ok=True)

# Task lifecycle
PENDING   = "pending"     # not yet runnable (deps not met)
READY     = "ready"       # deps satisfied, waiting for execution
RUNNING   = "running"
COMPLETED = "completed"
FAILED    = "failed"
SKIPPED   = "skipped"     # dependency failed → this can't run


class TaskGraph:
    def __init__(self, goal: str = "", graph_id: Optional[str] = None):
        self.id = graph_id or str(uuid.uuid4())
        self.goal = goal
        self.created_at = datetime.datetime.now().isoformat()
        self.tasks: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    # --- construction ---------------------------------------------------------

    def add(
        self,
        kind: str,
        params: Optional[Dict] = None,
        depends_on: Optional[List[str]] = None,
        description: str = "",
        agent: str = "default",
    ) -> str:
        """Add a sub-task. Returns its id."""
        task_id = str(uuid.uuid4())[:8]
        with self._lock:
            self.tasks[task_id] = {
                "id":          task_id,
                "kind":        kind,               # e.g. "search", "fetch_url", "summarise"
                "params":      params or {},
                "depends_on":  list(depends_on or []),
                "description": description or kind,
                "agent":       agent,              # which sub-agent handles it (see agent_manager)
                "status":      PENDING,
                "result":      None,
                "error":       None,
                "created_at":  datetime.datetime.now().isoformat(),
                "started_at":  None,
                "completed_at": None,
            }
        self._refresh_ready_statuses()
        return task_id

    # --- execution helpers ----------------------------------------------------

    def _refresh_ready_statuses(self):
        """Promote PENDING→READY when all deps are COMPLETED."""
        with self._lock:
            for t in self.tasks.values():
                if t["status"] != PENDING:
                    continue
                if not t["depends_on"]:
                    t["status"] = READY
                    continue
                dep_statuses = [self.tasks[d]["status"] for d in t["depends_on"] if d in self.tasks]
                if all(s == COMPLETED for s in dep_statuses):
                    t["status"] = READY
                elif any(s == FAILED for s in dep_statuses):
                    t["status"] = SKIPPED  # dep failed — can't run

    def ready_tasks(self) -> List[Dict]:
        """Tasks currently ready to execute (deps satisfied, not yet started)."""
        self._refresh_ready_statuses()
        with self._lock:
            return [dict(t) for t in self.tasks.values() if t["status"] == READY]

    def start(self, task_id: str):
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]["status"] = RUNNING
                self.tasks[task_id]["started_at"] = datetime.datetime.now().isoformat()

    def complete(self, task_id: str, result: Any):
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]["status"] = COMPLETED
                self.tasks[task_id]["result"] = result
                self.tasks[task_id]["completed_at"] = datetime.datetime.now().isoformat()
        self._refresh_ready_statuses()

    def fail(self, task_id: str, error: str):
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]["status"] = FAILED
                self.tasks[task_id]["error"] = str(error)[:500]
                self.tasks[task_id]["completed_at"] = datetime.datetime.now().isoformat()
        self._refresh_ready_statuses()

    def get_input(self, task_id: str) -> Dict:
        """Resolve a task's parameters, substituting {dep_id.result} placeholders
        with the completed result of that dependency. Lets you chain tasks
        without knowing upstream results at graph-build time.
        """
        with self._lock:
            t = self.tasks.get(task_id)
            if not t:
                return {}
            resolved = dict(t["params"])
            for dep_id in t["depends_on"]:
                dep = self.tasks.get(dep_id)
                if not dep or dep["status"] != COMPLETED:
                    continue
                for k, v in list(resolved.items()):
                    if isinstance(v, str) and f"{{{dep_id}}}" in v:
                        resolved[k] = v.replace(f"{{{dep_id}}}", str(dep["result"])[:4000])
            resolved["_deps"] = {d: self.tasks[d]["result"] for d in t["depends_on"] if d in self.tasks}
            return resolved

    # --- introspection --------------------------------------------------------

    def done(self) -> bool:
        with self._lock:
            return all(t["status"] in (COMPLETED, FAILED, SKIPPED) for t in self.tasks.values())

    def succeeded(self) -> bool:
        with self._lock:
            return all(t["status"] == COMPLETED for t in self.tasks.values())

    def summary(self) -> Dict:
        """Summary usable for UI / logs."""
        with self._lock:
            by_status: Dict[str, int] = {}
            for t in self.tasks.values():
                by_status[t["status"]] = by_status.get(t["status"], 0) + 1
            return {
                "id":           self.id,
                "goal":         self.goal,
                "created_at":   self.created_at,
                "total":        len(self.tasks),
                "by_status":    by_status,
                "done":         self.done(),
                "succeeded":    self.succeeded(),
            }

    def final_outputs(self) -> Dict[str, Any]:
        """Return results of every completed task keyed by task id."""
        with self._lock:
            return {tid: t["result"] for tid, t in self.tasks.items() if t["status"] == COMPLETED}

    def leaf_results(self) -> List[Any]:
        """Results of leaf tasks (no downstream dependents) — usually the 'final answer'."""
        with self._lock:
            downstream: Dict[str, int] = {tid: 0 for tid in self.tasks}
            for t in self.tasks.values():
                for d in t["depends_on"]:
                    if d in downstream:
                        downstream[d] += 1
            return [
                self.tasks[tid]["result"]
                for tid, n in downstream.items()
                if n == 0 and self.tasks[tid]["status"] == COMPLETED
            ]

    # --- persistence ----------------------------------------------------------

    def _path(self) -> str:
        return os.path.join(TASK_GRAPHS_DIR, f"{self.id}.json")

    def save(self):
        with self._lock:
            data = {
                "id":         self.id,
                "goal":       self.goal,
                "created_at": self.created_at,
                "tasks":      self.tasks,
            }
        try:
            with open(self._path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[task_graph] save failed: {e}")

    @classmethod
    def load(cls, graph_id: str) -> Optional["TaskGraph"]:
        path = os.path.join(TASK_GRAPHS_DIR, f"{graph_id}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        g = cls(goal=data.get("goal", ""), graph_id=data.get("id"))
        g.created_at = data.get("created_at", g.created_at)
        g.tasks = data.get("tasks", {})
        return g

    @classmethod
    def list_all(cls) -> List[Dict]:
        """Quick listing for the /graphs endpoint."""
        out = []
        if not os.path.exists(TASK_GRAPHS_DIR):
            return out
        for fname in sorted(os.listdir(TASK_GRAPHS_DIR), reverse=True)[:50]:
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(TASK_GRAPHS_DIR, fname), "r", encoding="utf-8") as f:
                    d = json.load(f)
                tasks = d.get("tasks", {})
                by_status: Dict[str, int] = {}
                for t in tasks.values():
                    by_status[t["status"]] = by_status.get(t["status"], 0) + 1
                out.append({
                    "id":         d.get("id"),
                    "goal":       d.get("goal", ""),
                    "created_at": d.get("created_at", ""),
                    "total":      len(tasks),
                    "by_status":  by_status,
                })
            except Exception:
                continue
        return out


# =============================================================================
# GRAPH BUILDER — convenience for LLM-produced JSON plans
# =============================================================================

def graph_from_plan(goal: str, plan: List[Dict]) -> TaskGraph:
    """Build a TaskGraph from a plan produced by brain_orchestrator's planner.

    plan = [
        {"id": "step1", "kind": "search", "params": {...}, "depends_on": []},
        {"id": "step2", "kind": "summarise", "params": {...}, "depends_on": ["step1"]},
    ]
    """
    g = TaskGraph(goal=goal)
    # two-pass because LLM plan uses temporary "id"s that we need to map to real uuids
    id_map: Dict[str, str] = {}
    for step in plan:
        tmp_id = step.get("id", str(uuid.uuid4())[:8])
        real_deps = [id_map.get(d, d) for d in (step.get("depends_on") or [])]
        real_id = g.add(
            kind=step.get("kind", "unknown"),
            params=step.get("params") or {},
            depends_on=real_deps,
            description=step.get("description", ""),
            agent=step.get("agent", "default"),
        )
        id_map[tmp_id] = real_id
    return g


# =============================================================================
# SMOKE TEST
# =============================================================================
if __name__ == "__main__":
    g = TaskGraph(goal="write a blog post about vector databases")
    a = g.add("search",       {"query": "vector databases 2026"})
    b = g.add("fetch_url",    {"url": "{search.top}"}, depends_on=[a])
    c = g.add("summarise",    {"text": "{fetch.body}"}, depends_on=[b])
    d = g.add("write_file",   {"path": "post.md", "content": "{summarise.out}"}, depends_on=[c])

    print(f"Before any execution, ready: {[t['kind'] for t in g.ready_tasks()]}")
    g.start(a); g.complete(a, "https://example.com/article")
    print(f"After a completes,    ready: {[t['kind'] for t in g.ready_tasks()]}")
    g.start(b); g.complete(b, "lots of page content...")
    print(f"After b completes,    ready: {[t['kind'] for t in g.ready_tasks()]}")
    g.start(c); g.fail(c, "LLM timeout")
    print(f"After c fails,  task d status: {g.tasks[d]['status']}")
    print(f"\nSummary: {json.dumps(g.summary(), indent=2)}")
    g.save()
    print(f"Saved to {g._path()}")
