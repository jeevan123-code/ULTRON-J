"""
decision_engine.py — The brain of Ultron-J's autonomous agent system. ULTIMATE.

ULTIMATE UPGRADES over previous version:
- Goal dependencies: goals can require other goals to complete first
- Goal templates: pre-built structures for research, code review, daily planning
- Urgency decay: goals become MORE urgent the longer they sit pending
- Conflict detection: flag when two goals contradict each other
- Success criteria: explicit, checkable criteria for each goal
- Richer planning: task dependencies, estimated duration, resource hints
- Execution scoring: track which plan strategies succeed most
- Better working memory: includes perception and personality context
- Goal archiving: completed goals compressed into monthly archives
"""

import json
import os
import datetime
import threading
import uuid
from enum import Enum
from typing import Optional

# Atomic state writes (survives OneDrive sync lock); falls back to plain
# write if memory.py somehow can't import (decision_engine boots very early).
try:
    from memory import atomic_json_write
except Exception:
    def atomic_json_write(filepath, data):
        with open(filepath, "w", encoding="utf-8") as _f:
            json.dump(data, _f, indent=2, ensure_ascii=False)

# ── File paths ────────────────────────────────────────────────────────────────
_BASE_DIR           = os.path.dirname(os.path.abspath(__file__))
GOALS_FILE          = os.path.join(_BASE_DIR, "goals.json")
GOALS_ARCHIVE_FILE  = os.path.join(_BASE_DIR, "goals_archive.json")
WORKING_MEMORY_FILE = os.path.join(_BASE_DIR, "working_memory.json")
EXECUTION_LOG_FILE  = os.path.join(_BASE_DIR, "execution_log.json")
AGENT_STATE_FILE    = os.path.join(_BASE_DIR, "agent_state.json")

# =============================================================================
# ENUMS
# =============================================================================

class GoalStatus(str, Enum):
    PENDING    = "pending"
    ACTIVE     = "active"
    PLANNING   = "planning"
    EXECUTING  = "executing"
    EVALUATING = "evaluating"
    COMPLETED  = "completed"
    FAILED     = "failed"
    PAUSED     = "paused"
    BLOCKED    = "blocked"      # NEW: blocked by dependency
    ARCHIVED   = "archived"     # NEW: moved to archive

class TaskStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    SUCCESS  = "success"
    FAILED   = "failed"
    SKIPPED  = "skipped"
    RETRYING = "retrying"
    BLOCKED  = "blocked"        # NEW: waiting for dependency

class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"

# =============================================================================
# SAFETY LAYER — unchanged + hardened
# =============================================================================

DANGEROUS_PATTERNS = [
    "rm -rf", "format", "delete system", "wipe",
    "sudo rm", "drop database", "shutdown", "reboot",
    ":(){:|:&};:", "fork bomb", "del /f /s /q",
    "mkfs", "dd if=/dev/zero", "chmod -R 777 /",
]

ALLOWED_COMMANDS = {
    "file_read", "file_write", "file_list", "search_web",
    "search_local", "ask_llm", "run_python", "api_call",
    "memory_store", "memory_fetch", "analyze", "summarize",
    "create_file", "append_file", "move_file",
    "web_scrape", "run_code", "git_status",       # NEW tools
    "note_create", "weather_fetch", "calculate",  # NEW tools
    # Aligned 2026-05-11: every action_type that action_engine.execute_action
    # actually dispatches must be allow-listed; otherwise safety_check rejects
    # legit calls (intent_router.execute_intent → execute_action) with
    # "Action 'X' not in allowed commands list." even though the executor
    # would handle them. Discovered while wiring open_and_search.
    "search_on_site", "open_url",
    "screenshot", "click", "type_text", "open_app",
    "run_command", "send_email", "hotkey",
    "scroll", "press_key",
    "get_clipboard", "set_clipboard",
    "get_window", "move_mouse",
    "delete_file", "delete_folder", "rename_file", "copy_file", "zip_folder",
}

RESTRICTED_PATHS = [
    "/etc", "/sys", "/proc", "/boot", "/root",
    "C:\\Windows", "C:\\System32",
]


def safety_check(action: dict) -> tuple:
    """Validate action before execution. Returns (is_safe, reason)."""
    action_type = action.get("type", "")
    params      = action.get("params", {})

    if action_type not in ALLOWED_COMMANDS:
        return False, f"Action '{action_type}' not in allowed commands list."

    # Scan command + content + code. run_python/run_code carry their payload
    # in params["code"] (action_engine.execute_action), so omitting it made the
    # dangerous-pattern layer a no-op for the normal code-execution path.
    cmd = (
        str(params.get("command", ""))
        + str(params.get("content", ""))
        + str(params.get("code", ""))
    )
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in cmd.lower():
            return False, f"Dangerous pattern detected: '{pattern}'"

    path = str(params.get("path", ""))
    for restricted in RESTRICTED_PATHS:
        if path.startswith(restricted):
            return False, f"Access to restricted path: {restricted}"

    content = params.get("content", "")
    if len(str(content)) > 10 * 1024 * 1024:
        return False, "Content too large (>10MB limit)"

    return True, "OK"

# =============================================================================
# WORKING MEMORY — extended with context fields
# =============================================================================

_wm_lock = threading.Lock()


def load_working_memory() -> dict:
    if os.path.exists(WORKING_MEMORY_FILE):
        try:
            with open(WORKING_MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "current_goal_id":    None,
        "current_step_index": 0,
        "current_step_name":  None,
        "last_result":        None,
        "last_result_success":None,
        "context":            {},
        "retry_count":        0,
        "loop_count":         0,
        "updated_at":         None,
        "perception_context": "",   # NEW: what Ultron currently sees
        "mood":               "IDLE", # NEW: current personality mood
        "session_goals":      [],   # NEW: goals created this session
        "blocked_goals":      [],   # NEW: goals waiting on dependencies
    }


def save_working_memory(wm: dict):
    wm["updated_at"] = datetime.datetime.now().isoformat()
    with _wm_lock:
        atomic_json_write(WORKING_MEMORY_FILE, wm)


def update_working_memory(**kwargs):
    wm = load_working_memory()
    wm.update(kwargs)
    save_working_memory(wm)

# =============================================================================
# GOAL MANAGEMENT
# =============================================================================

_goals_lock = threading.Lock()


def load_goals() -> list:
    if os.path.exists(GOALS_FILE):
        try:
            with open(GOALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_goals(goals: list):
    with _goals_lock:
        atomic_json_write(GOALS_FILE, goals)


def create_goal(
    title:          str,
    description:    str,
    priority:       str  = Priority.MEDIUM,
    source:         str  = "user",
    tags:           list = None,
    depends_on:     list = None,   # NEW: list of goal IDs that must complete first
    success_criteria: str = "",   # NEW: explicit criteria for "done"
    estimated_steps: int = 3,     # NEW: rough step count hint for planning
) -> dict:
    """Create a new goal and add to the goal queue."""
    goals = load_goals()
    goal  = {
        "id":               str(uuid.uuid4())[:8],
        "title":            title,
        "description":      description,
        "priority":         priority,
        "status":           GoalStatus.PENDING,
        "source":           source,
        "tags":             tags or [],
        "tasks":            [],
        "depends_on":       depends_on or [],      # NEW
        "success_criteria": success_criteria,      # NEW
        "estimated_steps":  estimated_steps,       # NEW
        "urgency_score":    0.0,                   # NEW: increases with age
        "conflicts_with":   [],                    # NEW: populated by conflict detection
        "created_at":       datetime.datetime.now().isoformat(),
        "updated_at":       datetime.datetime.now().isoformat(),
        "completed_at":     None,
        "retry_count":      0,
        "progress_pct":     0,
        "result_summary":   None,
        "execution_score":  None,                  # NEW: 0-10 score after completion
    }
    goals.append(goal)
    save_goals(goals)

    # Check for conflicts with existing goals
    _flag_conflicts(goal, goals)

    return goal


def get_goal(goal_id: str) -> Optional[dict]:
    for g in load_goals():
        if g["id"] == goal_id:
            return g
    return None


def update_goal(goal_id: str, **kwargs):
    goals = load_goals()
    for g in goals:
        if g["id"] == goal_id:
            g.update(kwargs)
            g["updated_at"] = datetime.datetime.now().isoformat()
    save_goals(goals)


def delete_goal(goal_id: str):
    goals = [g for g in load_goals() if g["id"] != goal_id]
    save_goals(goals)


def get_all_goals() -> list:
    return load_goals()


def get_active_goals() -> list:
    return [g for g in load_goals() if g["status"] in (
        GoalStatus.ACTIVE, GoalStatus.PLANNING,
        GoalStatus.EXECUTING, GoalStatus.EVALUATING,
    )]


def get_next_goal() -> Optional[dict]:
    """
    Get the highest-priority, unblocked pending goal.
    Applies urgency decay so older goals bubble up over time.
    """
    goals = load_goals()
    _apply_urgency_decay(goals)

    priority_order = {
        Priority.CRITICAL: 0,
        Priority.HIGH:     1,
        Priority.MEDIUM:   2,
        Priority.LOW:      3,
    }

    pending = [g for g in goals if g["status"] == GoalStatus.PENDING]

    # Check which ones are actually unblocked
    completed_ids = {g["id"] for g in goals if g["status"] == GoalStatus.COMPLETED}
    unblocked = []
    for g in pending:
        deps = g.get("depends_on", [])
        if all(dep_id in completed_ids for dep_id in deps):
            unblocked.append(g)
        else:
            # Mark blocked
            if g["status"] != GoalStatus.BLOCKED:
                update_goal(g["id"], status=GoalStatus.BLOCKED)

    if not unblocked:
        return None

    # Sort by urgency (includes time decay) then priority
    unblocked.sort(key=lambda g: (
        priority_order.get(g.get("priority", "medium"), 2),
        -g.get("urgency_score", 0),
    ))
    return unblocked[0]


def _apply_urgency_decay(goals: list):
    """
    Increase urgency score for goals that have been pending longer.
    Critical goals decay faster (become more urgent).
    Saves the updated urgency scores back to disk.
    """
    now     = datetime.datetime.now()
    changed = False
    for g in goals:
        if g["status"] not in (GoalStatus.PENDING, GoalStatus.BLOCKED):
            continue
        created = g.get("created_at", now.isoformat())
        try:
            age_hours = (now - datetime.datetime.fromisoformat(created)).total_seconds() / 3600
        except Exception:
            age_hours = 0
        decay_rate = {"critical": 2.0, "high": 1.0, "medium": 0.5, "low": 0.2}
        rate = decay_rate.get(g.get("priority", "medium"), 0.5)
        new_urgency = min(10.0, age_hours * rate)
        if abs(new_urgency - g.get("urgency_score", 0)) > 0.1:
            g["urgency_score"] = round(new_urgency, 2)
            changed = True
    if changed:
        save_goals(goals)


def _flag_conflicts(new_goal: dict, all_goals: list):
    """
    Detect if the new goal conflicts with existing active/pending goals.
    Simple keyword-based conflict detection.
    """
    conflict_pairs = [
        ("delete", "create"),
        ("remove", "add"),
        ("stop", "start"),
        ("disable", "enable"),
    ]
    new_desc = new_goal["description"].lower()
    conflicts = []

    for g in all_goals:
        if g["id"] == new_goal["id"]:
            continue
        if g["status"] not in (GoalStatus.PENDING, GoalStatus.ACTIVE):
            continue
        other_desc = g["description"].lower()
        for a, b in conflict_pairs:
            if (a in new_desc and b in other_desc) or (b in new_desc and a in other_desc):
                conflicts.append(g["id"])
                break

    if conflicts:
        new_goal["conflicts_with"] = conflicts
        save_goals(all_goals)

# =============================================================================
# GOAL TEMPLATES (NEW)
# =============================================================================

GOAL_TEMPLATES = {
    "research": {
        "description_template": "Research {topic} thoroughly: find sources, summarize findings, identify key insights",
        "priority": Priority.MEDIUM,
        "tags": ["research", "knowledge"],
        "estimated_steps": 5,
        "task_templates": [
            "Search for recent information about {topic}",
            "Search for expert opinions on {topic}",
            "Search Wikipedia for background on {topic}",
            "Synthesize findings into a structured summary",
            "Store key facts to knowledge base",
        ],
    },
    "code_review": {
        "description_template": "Review and improve code: {filename}",
        "priority": Priority.HIGH,
        "tags": ["code", "review"],
        "estimated_steps": 4,
        "task_templates": [
            "Read and understand the code in {filename}",
            "Identify bugs, inefficiencies, and code smells",
            "Suggest specific improvements with examples",
            "Check for security vulnerabilities",
        ],
    },
    "daily_plan": {
        "description_template": "Create today's priority plan and briefing",
        "priority": Priority.HIGH,
        "tags": ["planning", "daily"],
        "estimated_steps": 3,
        "task_templates": [
            "Review pending goals and their urgency scores",
            "Check system health and any overnight alerts",
            "Generate personalized priority plan for today",
        ],
    },
    "monitor": {
        "description_template": "Monitor {target} and alert on changes",
        "priority": Priority.MEDIUM,
        "tags": ["monitoring"],
        "estimated_steps": 2,
        "task_templates": [
            "Fetch current state of {target}",
            "Compare with last known state and report changes",
        ],
    },
}


def create_goal_from_template(template_name: str, **kwargs) -> Optional[dict]:
    """Create a goal from a template with variable substitution."""
    template = GOAL_TEMPLATES.get(template_name)
    if not template:
        return None

    desc = template["description_template"].format(**kwargs)
    task_templates = [t.format(**kwargs) for t in template.get("task_templates", [])]

    goal = create_goal(
        title=desc[:60],
        description=desc,
        priority=template.get("priority", Priority.MEDIUM),
        tags=template.get("tags", []),
        estimated_steps=len(task_templates),
        success_criteria=f"All {len(task_templates)} tasks completed successfully",
    )

    # Pre-populate tasks from template
    tasks = []
    for i, task_desc in enumerate(task_templates):
        tasks.append({
            "id":          f"task_{i}",
            "description": task_desc,
            "status":      TaskStatus.PENDING,
            "result":      None,
            "tool":        None,
            "attempts":    0,
        })

    update_goal(goal["id"], tasks=tasks)
    return get_goal(goal["id"])


def parse_goal_from_text(text: str) -> Optional[dict]:
    """Parse natural language text into goal fields."""
    text = text.strip()
    if not text:
        return None

    # Priority detection
    priority = Priority.MEDIUM
    tl = text.lower()
    if any(k in tl for k in ["urgent", "asap", "immediately", "critical", "emergency"]):
        priority = Priority.CRITICAL
    elif any(k in tl for k in ["important", "high priority", "soon"]):
        priority = Priority.HIGH
    elif any(k in tl for k in ["when you can", "low priority", "someday", "eventually"]):
        priority = Priority.LOW

    # Template detection
    template = None
    if any(k in tl for k in ["research", "find out", "look up", "investigate"]):
        template = "research"
    elif any(k in tl for k in ["review code", "check code", "fix bug", "debug"]):
        template = "code_review"
    elif any(k in tl for k in ["daily plan", "today's plan", "plan for today"]):
        template = "daily_plan"

    if template:
        return {"title": text[:60], "description": text, "priority": priority, "template": template}

    return {"title": text[:60], "description": text, "priority": priority}

# =============================================================================
# PLANNING SYSTEM — enhanced
# =============================================================================

def build_plan(goal: dict) -> list:
    """
    Build a step-by-step task plan for a goal.
    Uses goal description, tags, and template hints to create appropriate tasks.
    """
    desc   = (goal.get("description") or goal.get("title", "")).lower()
    tasks  = goal.get("tasks", [])

    # If tasks were pre-populated from a template, return them
    if tasks and any(t.get("status") == TaskStatus.PENDING for t in tasks):
        return tasks

    # Otherwise, auto-generate tasks from description
    steps = []

    def add_task(step_desc: str, tool: str = "ask_llm"):
        steps.append({
            "id":          f"step_{len(steps)}",
            "description": step_desc,
            "status":      TaskStatus.PENDING,
            "result":      None,
            "tool":        tool,
            "attempts":    0,
            "depends_on":  [steps[-1]["id"]] if steps else [],  # sequential by default
        })

    # Plan based on intent signals
    if any(k in desc for k in ["research", "find", "look up", "search"]):
        add_task(f"Search the web: {goal['title']}", "search_web")
        add_task("Search additional sources for verification", "search_local")
        add_task("Synthesize findings into a clear summary", "ask_llm")
        add_task("Store key findings to knowledge base", "memory_store")

    elif any(k in desc for k in ["write", "draft", "create", "generate"]):
        add_task("Gather context and requirements", "ask_llm")
        add_task(f"Draft initial version: {goal['title']}", "ask_llm")
        add_task("Review and refine the draft", "ask_llm")
        add_task("Save final output to file", "file_write")

    elif any(k in desc for k in ["code", "python", "script", "function"]):
        add_task("Analyze requirements and design approach", "ask_llm")
        add_task("Write the initial code", "ask_llm")
        add_task("Test the code logic", "run_code")
        add_task("Document and finalize", "ask_llm")

    elif any(k in desc for k in ["monitor", "watch", "track", "alert"]):
        add_task("Fetch current status", "search_web")
        add_task("Compare with baseline and identify changes", "analyze")
        add_task("Report findings", "ask_llm")

    elif any(k in desc for k in ["analyze", "evaluate", "assess", "review"]):
        add_task("Gather all relevant information", "search_web")
        add_task("Perform structured analysis", "analyze")
        add_task("Generate insights and recommendations", "ask_llm")

    else:
        # Generic plan
        add_task(f"Understand and clarify: {goal['title']}", "ask_llm")
        add_task("Execute the primary action", "ask_llm")
        add_task("Verify the result", "analyze")

    return steps

# =============================================================================
# EXECUTION ENGINE SUPPORT
# =============================================================================

_exec_log_lock = threading.Lock()


def log_execution(goal_id: str, step_id: str, action: str, result: str, success: bool):
    """Append to the execution log."""
    log = []
    if os.path.exists(EXECUTION_LOG_FILE):
        try:
            with open(EXECUTION_LOG_FILE, "r", encoding="utf-8") as f:
                log = json.load(f)
        except Exception:
            pass
    log.append({
        "goal_id":  goal_id,
        "step_id":  step_id,
        "action":   action,
        "result":   str(result)[:500],
        "success":  success,
        "at":       datetime.datetime.now().isoformat(),
    })
    if len(log) > 500:
        log = log[-500:]
    with _exec_log_lock:
        atomic_json_write(EXECUTION_LOG_FILE, log)


def get_execution_log(n: int = 20) -> list:
    if os.path.exists(EXECUTION_LOG_FILE):
        try:
            with open(EXECUTION_LOG_FILE, "r", encoding="utf-8") as f:
                log = json.load(f)
            return log[-n:]
        except Exception:
            pass
    return []


def evaluate_task_result(result: str, task: dict) -> bool:
    """Simple heuristic to evaluate if a task succeeded."""
    if not result:
        return False
    result_lower = result.lower()
    fail_signals = [
        "error", "failed", "exception", "traceback",
        "not found", "404", "timeout", "refused",
        "could not", "unable to", "no results",
    ]
    if any(s in result_lower for s in fail_signals):
        return False
    return len(result.strip()) > 10


def calculate_goal_progress(goal: dict) -> int:
    """Calculate completion percentage for a goal."""
    tasks = goal.get("tasks", [])
    if not tasks:
        return 0
    done = sum(1 for t in tasks if t.get("status") in (TaskStatus.SUCCESS, TaskStatus.SKIPPED))
    return int((done / len(tasks)) * 100)

# =============================================================================
# AGENT STATE
# =============================================================================

_state_lock = threading.Lock()


def load_agent_state() -> dict:
    if os.path.exists(AGENT_STATE_FILE):
        try:
            with open(AGENT_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "mode": "idle",
        "loop_cycle": 0,
        "last_goal_id": None,
        "goals_completed": 0,
        "goals_failed": 0,
        "uptime_start": datetime.datetime.now().isoformat(),
    }


def save_agent_state(state: dict):
    state["updated_at"] = datetime.datetime.now().isoformat()
    with _state_lock:
        atomic_json_write(AGENT_STATE_FILE, state)


def update_agent_mode(mode: str):
    state = load_agent_state()
    state["mode"] = mode
    save_agent_state(state)


def decide_next_action(context: dict) -> dict:
    """
    Core decision function: given observations, decide the next agent action.
    Returns an action dict.
    """
    obs = context.get("observation", {})

    # Check for active goals first
    active = get_active_goals()
    if active:
        g = active[0]
        tasks = g.get("tasks", [])
        next_task = next((t for t in tasks if t.get("status") == TaskStatus.PENDING), None)
        if next_task:
            return {"action": "execute_task", "goal_id": g["id"], "task": next_task}
        return {"action": "evaluate_goal", "goal_id": g["id"]}

    # Get next pending goal
    next_goal = get_next_goal()
    if next_goal:
        return {"action": "start_goal", "goal_id": next_goal["id"]}

    # Nothing to do — self-evaluate
    state = load_agent_state()
    if state.get("loop_cycle", 0) % 12 == 0:   # every ~hour at 5min intervals
        return {"action": "self_evaluate"}

    return {"action": "observe"}
