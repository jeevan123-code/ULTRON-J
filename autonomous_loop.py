"""
autonomous_loop.py — The continuous observe → decide → plan → act → evaluate → reflect loop.
ULTIMATE version.

ULTIMATE UPGRADES:
- Phase 6: REFLECT — after every N goals, analyze performance and grow
- Proactive predictions: "you usually work on X at this time"
- Daily planning session: morning goals + evening review generation
- Resource optimization: select model tier based on task complexity
- Network connectivity monitoring: knows when offline
- Personality mood sync: updates mood based on what's happening
- Better suggestion quality: contextual, not generic
- Clipboard awareness: reacts to what Jeevan copies
- Self-healing: detects its own errors and recovers
"""

import datetime
import json
import os
import threading
import time

from decision_engine import (
    decide_next_action, GoalStatus, TaskStatus, Priority,
    create_goal, get_goal, update_goal, get_active_goals,
    get_next_goal, update_agent_mode, load_agent_state,
    save_agent_state, log_execution, update_working_memory,
    load_working_memory, get_execution_log, build_plan,
    parse_goal_from_text, create_goal_from_template,
)
from action_engine import (
    start_goal_execution, execute_goal_step, finish_goal_evaluation,
    get_knowledge_stats, store_knowledge, recall_knowledge,
    load_tool_stats, execute_action, fetch_weather,
)

try:
    from config import (
        JEEVAN_NAME, JEEVAN_LOCATION, HEARTBEAT_INTERVAL,
        CONNECTIVITY_CHECK_HOSTS, CONNECTIVITY_TIMEOUT,
        CONNECTIVITY_CHECK_INTERVAL,
    )
    from system_monitor import (
        push_alert, get_memory_usage, get_disk_usage,
        get_desktop_files, get_ollama_models,
    )
    from memory import record_activity, get_pattern_context, get_stale_projects, store_episode
    from personality import (
        trigger_mood_change, sync_time_mood,
        drain_energy, restore_energy, reset_daily_energy,
        get_mood, get_mood_phrase,
    )
    from perception import pop_fs_suggestions, pop_clipboard_suggestions, build_perception_context
    from reflection import run_reflection, should_reflect, add_reflection, generate_session_summary
except ImportError as e:
    print(f"[Loop] Import warning: {e}")
    JEEVAN_NAME              = "Jeevan"
    JEEVAN_LOCATION          = "Hyderabad, Telangana, India"
    HEARTBEAT_INTERVAL       = 300
    CONNECTIVITY_CHECK_HOSTS = ["8.8.8.8"]
    CONNECTIVITY_TIMEOUT     = 3
    CONNECTIVITY_CHECK_INTERVAL = 60
    def push_alert(msg): print(f"[ALERT] {msg}")
    def get_memory_usage(): return {}
    def get_disk_usage(): return {}
    def get_desktop_files(): return []
    def get_ollama_models(): return []
    def record_activity(**kwargs): pass
    def get_pattern_context(): return ""
    def get_stale_projects(**kwargs): return []
    def store_episode(**kwargs): return ""
    def trigger_mood_change(e): pass
    def sync_time_mood(): pass
    def drain_energy(a=0.05): pass
    def restore_energy(a=0.1): pass
    def reset_daily_energy(): pass
    def get_mood(): return "IDLE"
    def get_mood_phrase(m=None): return "Monitoring."
    def pop_fs_suggestions(): return []
    def pop_clipboard_suggestions(): return []
    def build_perception_context(): return ""
    def run_reflection(): return {}
    def should_reflect(): return False
    def add_reflection(**kwargs): pass
    def generate_session_summary(**kwargs): return {}

_BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
SELF_IMPROVE_LOG  = os.path.join(_BASE_DIR, "self_improvement_log.json")
LOOP_STATUS_FILE  = os.path.join(_BASE_DIR, "loop_status.json")
DAILY_PLAN_FILE   = os.path.join(_BASE_DIR, "daily_plan.json")
NET_STATUS_FILE   = os.path.join(_BASE_DIR, "network_status.json")

# =============================================================================
# LOOP STATE
# =============================================================================

_loop_running     = False
_loop_thread      = None
_loop_lock        = threading.Lock()
_agent_suggestions = []
_suggestions_lock  = threading.Lock()

# Network state
_online           = True
_net_lock         = threading.Lock()

# Daily state
_last_briefing_hour = -1
_last_reflection_at = None
_goals_since_reflect = 0


def push_agent_suggestion(msg: str, priority: str = "normal"):
    with _suggestions_lock:
        _agent_suggestions.append({
            "time":     datetime.datetime.now().strftime("%H:%M:%S"),
            "msg":      msg,
            "priority": priority,
        })
        if len(_agent_suggestions) > 30:
            _agent_suggestions.pop(0)


def pop_agent_suggestions() -> list:
    with _suggestions_lock:
        out = list(_agent_suggestions)
        _agent_suggestions.clear()
    return out


def save_loop_status(status: dict):
    status["updated_at"] = datetime.datetime.now().isoformat()
    from memory import atomic_json_write
    atomic_json_write(LOOP_STATUS_FILE, status)


def load_loop_status() -> dict:
    if os.path.exists(LOOP_STATUS_FILE):
        # Phase 7.1 — narrowed from blanket `except Exception`. These are
        # the only failure modes that can occur on a json.load of a known
        # path: file vanished mid-read, OS-level error, or partial write
        # leaving non-JSON content. Anything else is a real bug we want to
        # see, not swallow.
        try:
            with open(LOOP_STATUS_FILE, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return {"running": False, "cycle": 0, "phase": "idle", "last_action": None}


def is_loop_running() -> bool:
    with _loop_lock:
        return _loop_running


def is_online() -> bool:
    with _net_lock:
        return _online

# =============================================================================
# NETWORK MONITORING
# =============================================================================

def _check_connectivity() -> bool:
    """Check if internet is reachable."""
    import socket
    for host in CONNECTIVITY_CHECK_HOSTS:
        # Phase 7.1 — narrowed. Connectivity probes legitimately fail
        # in a small set of ways (timeout, DNS, refused, network down).
        # We deliberately swallow these -- the function's whole purpose
        # is to return True/False on reachability, not to log.
        try:
            socket.setdefaulttimeout(CONNECTIVITY_TIMEOUT)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, 53))
            return True
        except (OSError, socket.timeout, socket.gaierror):
            pass
    return False


def _network_monitor_loop():
    """Background thread: monitors internet connectivity."""
    global _online
    while _loop_running:
        was_online = _online
        now_online = _check_connectivity()
        with _net_lock:
            _online = now_online
        if was_online and not now_online:
            push_alert("⚠️ Internet connection lost. Switching to local mode recommended.")
            push_agent_suggestion(
                f"⚠️ Network went offline. Web search won't work. "
                f"Consider switching to local mode.",
                priority="high"
            )
            trigger_mood_change("error_detected")
        elif not was_online and now_online:
            push_alert("✅ Internet connection restored.")
            push_agent_suggestion("✅ Back online. Full capabilities restored.")
        time.sleep(CONNECTIVITY_CHECK_INTERVAL)

# =============================================================================
# PHASE 1: OBSERVE — scan environment (enhanced)
# =============================================================================

def _phase7_unified_tick(obs: dict) -> None:
    """Phase 7 hook — invoke mind_tick to unify Phase 3c/4/6 surfaces.

    Stamps the result into `obs["phase7_summary"]` so downstream
    make_decision can react to it (e.g., bump priority if a briefing
    just fired). On exception, records the error in `obs["phase7_error"]`
    instead of propagating — the consciousness loop must not crash.
    """
    import os as _os_p7
    if _os_p7.environ.get("ULTRON_PHASE7_ENABLED", "0") != "1":
        return
    try:
        import mind_tick
        obs["phase7_summary"] = mind_tick.tick()
    except Exception as e:
        obs["phase7_error"] = repr(e)
        try:
            with open("ultron_log.txt", "a") as _f:
                _f.write(f"[phase7][cycle_hook] {e!r}\n")
        except Exception:
            pass


def observe_environment() -> dict:
    """Gather current state of the environment. Enhanced version."""
    now = datetime.datetime.now()
    obs = {
        "timestamp":    now.isoformat(),
        "time_of_day":  now.strftime("%H:%M"),
        "day":          now.strftime("%A"),
        "hour":         now.hour,
        "date":         now.strftime("%Y-%m-%d"),
        "online":       is_online(),
    }

    # System health
    mem = get_memory_usage()
    obs["ram_pct"]      = mem.get("percent", 0)
    obs["ram_critical"] = mem.get("percent", 0) > 90
    obs["ram_gb_free"]  = mem.get("free_gb", 0)

    disk = get_disk_usage()
    # Phase 3.1 fix — exclude pseudo-filesystems and snap mounts. Snap
    # packages mount as squashfs images that are 100% full BY DESIGN
    # (read-only loop devices), so the old `any > 92` check fired every
    # cycle on a system with any snap installed and short-circuited the
    # entire goal-execution path into an alert spam.
    # A path denylist can never enumerate every read-only pseudo-mount
    # (AppImage, flatpak, loop devices, container bind-mounts), and a single
    # unknown 100%-full read-only mount flips disk_critical and short-circuits
    # the whole goal loop into alert-spam. Instead, treat a mount as a real
    # disk only if it is not an obvious pseudo-mount AND is actually writable —
    # read-only loop/squashfs mounts (always 100% full by design) are excluded.
    _PSEUDO_MOUNT_PREFIXES = ("/snap/", "/var/lib/docker/", "/proc/", "/sys/", "/dev/")
    def _is_real_disk(mountpoint: str) -> bool:
        if any(mountpoint.startswith(p) for p in _PSEUDO_MOUNT_PREFIXES):
            return False
        return os.access(mountpoint, os.W_OK)
    obs["disk_critical"] = any(
        d.get("percent", 0) > 92
        for mp, d in disk.items()
        if _is_real_disk(mp)
    )

    # Desktop
    desktop = get_desktop_files()
    obs["desktop_count"] = len(desktop)
    obs["desktop_files"] = [f["name"] for f in desktop[:10]]

    # Goals
    from decision_engine import load_goals
    goals = load_goals()
    obs["pending_goals"]    = len([g for g in goals if g["status"] == GoalStatus.PENDING])
    obs["active_goals"]     = len([g for g in goals if g["status"] in (GoalStatus.ACTIVE, GoalStatus.EXECUTING)])
    obs["completed_today"]  = len([
        g for g in goals
        if g["status"] == GoalStatus.COMPLETED
        and g.get("completed_at", "").startswith(now.strftime("%Y-%m-%d"))
    ])
    obs["failed_today"]     = len([
        g for g in goals
        if g["status"] == GoalStatus.FAILED
        and g.get("updated_at", "").startswith(now.strftime("%Y-%m-%d"))
    ])

    # Knowledge
    kb_stats = get_knowledge_stats()
    obs["knowledge_entries"] = kb_stats.get("total_entries", 0)

    # Ollama
    obs["ollama_models"] = get_ollama_models()

    # Perception context
    obs["perception_context"] = build_perception_context()

    # Current mood
    obs["current_mood"] = get_mood()

    # Computer control availability
    try:
        from computer_control import get_computer_status
        cc = get_computer_status()
        obs["computer_control_available"] = cc.get("pyautogui", False)
        obs["email_available"]            = cc.get("email", False)
    except ImportError:
        obs["computer_control_available"] = False
        obs["email_available"]            = False

    return obs

# =============================================================================
# PHASE 2: DECIDE
# =============================================================================

def make_decision(observation: dict) -> dict:
    if observation.get("ram_critical"):
        trigger_mood_change("error_detected")
        push_alert(f"⚡ RAM critical: {observation.get('ram_pct')}% used! Pausing heavy tasks.")
        return {"action": "alert", "msg": "RAM critical — pausing heavy operations"}

    if observation.get("disk_critical"):
        push_alert("⚡ Disk almost full! Cleanup needed.")
        return {"action": "alert", "msg": "Disk critical — cleanup needed"}

    if not observation.get("online", True):
        # Offline: still process local goals
        active = get_active_goals()
        if active:
            return decide_next_action({"observation": observation})
        return {"action": "observe"}

    return decide_next_action({"observation": observation})

# =============================================================================
# PHASE 3: PLAN
# =============================================================================

def plan_for_decision(decision: dict) -> dict:
    action = decision.get("action")
    if action == "start_goal":
        goal_id = decision.get("goal_id")
        if goal_id:
            start_goal_execution(goal_id)
            trigger_mood_change("goal_started")
            return {"planned": True, "goal_id": goal_id, "action": "execute_next_task"}
    elif action == "execute_task":
        return {
            "planned": True,
            "goal_id": decision.get("goal_id"),
            "task":    decision.get("task"),
            "action":  "execute_task",
        }
    elif action == "evaluate_goal":
        return {
            "planned":  True,
            "goal_id":  decision.get("goal_id"),
            "action":   "evaluate_goal",
        }
    elif action == "self_evaluate":
        return {"planned": True, "action": "self_evaluate"}
    return {"planned": False, "action": "observe"}

# =============================================================================
# PHASE 4: ACT
# =============================================================================

def act_on_plan(plan: dict) -> str:
    action  = plan.get("action")
    goal_id = plan.get("goal_id")
    result  = "No action taken"

    try:
        if action == "execute_next_task" and goal_id:
            goal  = get_goal(goal_id)
            tasks = goal.get("tasks", []) if goal else []
            next_task = next((t for t in tasks if t.get("status") == TaskStatus.PENDING), None)
            if next_task:
                out = execute_goal_step(goal_id, next_task)
                # Update task status in goals
                _update_task_in_goal(goal_id, next_task["id"],
                                     TaskStatus.SUCCESS if out.get("success") else TaskStatus.FAILED,
                                     out.get("result", out.get("error", "")))
                drain_energy(0.05)
                result = f"Task executed: {next_task.get('description', '')[:60]}"
            else:
                result = "No pending tasks in goal"

        elif action == "execute_task" and goal_id:
            task = plan.get("task", {})
            out  = execute_goal_step(goal_id, task)
            _update_task_in_goal(goal_id, task.get("id", ""),
                                 TaskStatus.SUCCESS if out.get("success") else TaskStatus.FAILED,
                                 out.get("result", ""))
            drain_energy(0.05)
            result = f"Task: {task.get('description', '')[:60]} — {'✓' if out.get('success') else '✗'}"

        elif action == "evaluate_goal" and goal_id:
            goal = get_goal(goal_id)
            if goal:
                tasks   = goal.get("tasks", [])
                summary = f"Completed {sum(1 for t in tasks if t.get('status') == TaskStatus.SUCCESS)}/{len(tasks)} tasks"
                success = finish_goal_evaluation(goal_id, summary)
                if success:
                    trigger_mood_change("goal_completed")
                    push_agent_suggestion(
                        f"✅ Goal completed: '{goal['title']}'. {summary}",
                        priority="high"
                    )
                    # Store episode
                    store_episode(
                        kind="task",
                        summary=f"Completed goal: {goal['title']}",
                        detail=summary,
                        valence=0.8,
                        importance=0.7,
                    )
                    global _goals_since_reflect
                    _goals_since_reflect += 1
                else:
                    trigger_mood_change("goal_failed")
                    push_agent_suggestion(
                        f"⚠️ Goal failed: '{goal['title']}'. Will retry if attempts remain.",
                        priority="high"
                    )
                result = summary

        elif action == "self_evaluate":
            result = _run_self_evaluation()

    except Exception as e:
        result = f"Act error: {str(e)[:200]}"
        push_alert(f"⚡ Loop act error: {str(e)[:100]}")

    return result

# =============================================================================
# PHASE 5: EVALUATE & PHASE 6: REFLECT (NEW)
# =============================================================================

def evaluate_result(result: str, plan: dict) -> bool:
    """Evaluate if the act phase succeeded."""
    if not result:
        return False
    fail_signals = ["error", "failed", "exception", "timeout", "refused", "blocked"]
    return not any(s in result.lower() for s in fail_signals)


def maybe_reflect():
    """Trigger reflection if conditions are met."""
    global _goals_since_reflect
    if should_reflect() or _goals_since_reflect >= 5:
        try:
            push_agent_suggestion("🧠 Running self-reflection cycle...", priority="low")
            result = run_reflection()
            _goals_since_reflect = 0
            metrics = result.get("metrics", {})
            push_agent_suggestion(
                f"🧠 Reflection complete. Success rate: {metrics.get('success_rate_pct', '?')}%. "
                f"Found {len(result.get('gaps', []))} improvement areas.",
                priority="low"
            )
        except Exception as e:
            print(f"[Loop] Reflection error: {e}")

# =============================================================================
# HELPER: update task inside a goal
# =============================================================================

def _update_task_in_goal(goal_id: str, task_id: str, status: str, result: str):
    """Update the status and result of a specific task inside a goal."""
    goal = get_goal(goal_id)
    if not goal:
        return
    tasks = goal.get("tasks", [])
    for t in tasks:
        if t.get("id") == task_id:
            t["status"] = status
            t["result"] = result[:500]
            t["attempts"] = t.get("attempts", 0) + 1
            break
    from decision_engine import calculate_goal_progress
    progress = calculate_goal_progress({"tasks": tasks})
    update_goal(goal_id, tasks=tasks, progress_pct=progress)

# =============================================================================
# PROACTIVE INTELLIGENCE
# =============================================================================

def _run_self_evaluation() -> str:
    """Analyze recent performance and generate self-improvement suggestions."""
    log = get_execution_log(20)
    if not log:
        return "No recent actions to evaluate."

    success_count = sum(1 for e in log if e.get("success"))
    fail_count    = len(log) - success_count
    rate          = round(success_count / max(len(log), 1) * 100)

    log_entry = {
        "at":          datetime.datetime.now().isoformat(),
        "rate":        rate,
        "success":     success_count,
        "fail":        fail_count,
        "suggestions": [],
    }

    if fail_count > success_count:
        log_entry["suggestions"].append("High failure rate — reviewing tool configurations recommended")
        push_agent_suggestion(
            f"⚠️ Self-evaluation: {rate}% success rate on last {len(log)} actions. "
            f"Reviewing tools.",
            priority="high"
        )
    else:
        push_agent_suggestion(
            f"✅ Self-evaluation: {rate}% success rate. Systems nominal.",
            priority="low"
        )

    _append_self_improve_log(log_entry)
    return f"Self-evaluation: {rate}% success rate ({success_count} ok, {fail_count} failed)"


def _append_self_improve_log(entry: dict):
    log = []
    if os.path.exists(SELF_IMPROVE_LOG):
        # Phase 7.1 — narrowed. Partial-write / vanished file is the
        # expected failure; recover gracefully and overwrite.
        try:
            with open(SELF_IMPROVE_LOG, "r") as f:
                log = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    log.append(entry)
    if len(log) > 100:
        log = log[-100:]
    with open(SELF_IMPROVE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def get_self_improvement_log() -> list:
    if os.path.exists(SELF_IMPROVE_LOG):
        # Phase 7.1 — narrowed (same rationale as _append_self_improve_log).
        try:
            with open(SELF_IMPROVE_LOG, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return []


def _generate_proactive_suggestions(obs: dict):
    """
    Based on environment observations, proactively suggest things to Jeevan.
    """
    hour = obs.get("hour", 12)
    day  = obs.get("day", "Monday")

    # Morning briefing: generate daily plan
    if 6 <= hour < 10:
        pending = obs.get("pending_goals", 0)
        if pending > 0:
            push_agent_suggestion(
                f"Good morning {JEEVAN_NAME}. You have {pending} pending goal(s). "
                f"Want me to generate a priority plan for today?",
                priority="high"
            )

    # Evening review
    if 18 <= hour < 22:
        completed = obs.get("completed_today", 0)
        failed    = obs.get("failed_today", 0)
        if completed > 0 or failed > 0:
            push_agent_suggestion(
                f"Evening check-in: {completed} goal(s) completed, {failed} failed today. "
                f"Want a session summary?",
                priority="normal"
            )

    # Stale projects check (once a day)
    if hour == 9:
        # Phase 7.1 — was silent-pass. Now logs so we notice if
        # get_stale_projects starts throwing (real signal that memory
        # is mis-shaped).
        try:
            stale = get_stale_projects(days_threshold=7)
            for proj in stale[:2]:
                push_agent_suggestion(
                    f"📂 '{proj['project']}' hasn't been touched in {proj['days_ago']} days. "
                    f"Still active?",
                    priority="low"
                )
        except Exception as _e:
            try:
                from error_tracker import log_failure
                log_failure("autonomous_loop", "_morning_check_stale", _e)
            except Exception:
                pass

    # RAM warning
    if obs.get("ram_pct", 0) > 80:
        push_agent_suggestion(
            f"⚡ RAM at {obs['ram_pct']}%. Consider closing unused applications.",
            priority="high"
        )

    # Collect perception suggestions
    fs_suggestions  = pop_fs_suggestions()
    clip_suggestions = pop_clipboard_suggestions()
    for s in fs_suggestions:
        push_agent_suggestion(s["msg"], priority="normal")
    for s in clip_suggestions:
        push_agent_suggestion(s["msg"], priority="normal")

    # Computer control suggestions
    if obs.get("computer_control_available"):
        # Suggest opening browser for morning news
        if 6 <= hour < 9:
            push_agent_suggestion(
                "☀ Morning: I can open your browser, pull today's news, or run a system check. Just say the word.",
                priority="low"
            )
        # Suggest email check
        if obs.get("email_available") and hour == 9:
            push_agent_suggestion(
                "📧 Email is configured. I can send status reports or notifications on your behalf.",
                priority="low"
            )


def _generate_daily_plan(obs: dict):
    """Generate a daily goal plan based on pending goals and patterns."""
    from decision_engine import load_goals
    goals   = load_goals()
    pending = [g for g in goals if g["status"] in (GoalStatus.PENDING, GoalStatus.BLOCKED)]
    if not pending:
        return

    # Create a "daily plan" goal automatically
    plan_exists = any(
        "daily plan" in g.get("title", "").lower()
        and g.get("created_at", "").startswith(obs.get("date", ""))
        for g in goals
    )
    if not plan_exists:
        create_goal_from_template("daily_plan")


def _weather_morning_briefing():
    """Fetch weather and include in morning briefing.

    Phase 7.1 — the surrounding try/except used to silent-pass; now logs
    so a broken weather provider (rate limit, API change, network) shows
    up in error_log.json instead of being mistaken for "no briefing
    today".
    """
    try:
        weather = fetch_weather()
        if weather.get("success"):
            push_agent_suggestion(
                f"🌤️ Weather: {weather['description']}, {weather['temp_c']}°C in {JEEVAN_LOCATION}. "
                f"Humidity {weather['humidity']}%.",
                priority="normal"
            )
    except Exception as _e:
        try:
            from error_tracker import log_failure
            log_failure("autonomous_loop", "_weather_morning_briefing", _e)
        except Exception:
            pass

# =============================================================================
# MAIN AUTONOMOUS LOOP
# =============================================================================

def _continuous_loop():
    """
    The main observe → decide → plan → act → evaluate → reflect loop.
    Runs every HEARTBEAT_INTERVAL seconds.
    """
    global _last_briefing_hour, _loop_running

    print(f"[{_AGENT_NAME}] Autonomous loop started. Watching.")
    cycle = 0

    while _loop_running:
        try:
            # T28 — skip cycle if user is mid-conversation
            # Read from sys.modules to avoid re-importing app.py as a second
            # module object (which would re-run all module-level init code).
            # Phase 7.1 — narrowed. The only failures here are normal
            # Python attribute lookups + a sleep call; KeyError /
            # AttributeError are the documented failure modes.
            try:
                import sys as _sys
                _app = _sys.modules.get('__main__') or _sys.modules.get('app')
                _conv_active = getattr(_app, '_conversation_active', None)
                if _conv_active and _conv_active.is_set():
                    time.sleep(1)
                    continue
            except (AttributeError, KeyError):
                pass

            cycle += 1
            now  = datetime.datetime.now()
            hour = now.hour

            # Save loop status
            save_loop_status({
                "running":     True,
                "cycle":       cycle,
                "phase":       "observing",
                "last_action": now.isoformat(),
            })

            # Sync mood to time of day
            sync_time_mood()

            # PHASE 1: OBSERVE
            obs = observe_environment()

            # PHASE 7: unify Phase 3c / 4 / 6 surfaces into one tick.
            # Flag-gated; safe no-op when ULTRON_PHASE7_ENABLED is off.
            _phase7_unified_tick(obs)

            # PHASE 2: DECIDE
            decision = make_decision(obs)
            save_loop_status({"running": True, "cycle": cycle, "phase": "deciding"})

            # PHASE 3: PLAN
            plan = plan_for_decision(decision)
            save_loop_status({"running": True, "cycle": cycle, "phase": "planning"})

            # PHASE 4: ACT
            if plan.get("planned") and plan.get("action") != "observe":
                save_loop_status({"running": True, "cycle": cycle, "phase": "acting"})
                result = act_on_plan(plan)

                # PHASE 5: EVALUATE
                save_loop_status({"running": True, "cycle": cycle, "phase": "evaluating"})
                success = evaluate_result(result, plan)

                update_working_memory(
                    last_result=result,
                    last_result_success=success,
                    loop_count=cycle,
                    perception_context=obs.get("perception_context", ""),
                    mood=obs.get("current_mood", "IDLE"),
                )

            # PHASE 6: REFLECT (NEW — periodic)
            maybe_reflect()

            # Proactive intelligence
            _generate_proactive_suggestions(obs)

            # Morning briefing
            if 6 <= hour <= 10 and hour != _last_briefing_hour:
                _weather_morning_briefing()
                _generate_daily_plan(obs)
                _last_briefing_hour = hour
                restore_energy(0.1)     # morning = fresh energy

            # Daily energy reset at midnight
            if hour == 0 and now.minute < 5:
                reset_daily_energy()

            save_loop_status({"running": True, "cycle": cycle, "phase": "idle"})

        except Exception as e:
            print(f"[Loop] Cycle {cycle} error: {e}")
            push_alert(f"⚡ Loop error in cycle {cycle}: {str(e)[:100]}")

        time.sleep(HEARTBEAT_INTERVAL)

    save_loop_status({"running": False, "cycle": cycle, "phase": "stopped"})
    print(f"[{_AGENT_NAME}] Autonomous loop stopped.")


_AGENT_NAME = "Ultron-J"

# =============================================================================
# LIFECYCLE
# =============================================================================

def start_autonomous_loop() -> bool:
    global _loop_running, _loop_thread
    # Phase 4.1 — gate through loop_supervisor / config.LOOPS
    from loop_supervisor import loop_enabled
    if not loop_enabled("autonomous"):
        print("[autonomous] loop disabled by config.LOOPS — not starting")
        return False
    with _loop_lock:
        if _loop_running:
            return True
        _loop_running = True

    _loop_thread = threading.Thread(target=_continuous_loop, daemon=True, name="UltronMainLoop")
    _loop_thread.start()

    # Also start network monitor
    net_thread = threading.Thread(target=_network_monitor_loop, daemon=True, name="UltronNetMonitor")
    net_thread.start()

    return True


def stop_autonomous_loop():
    global _loop_running
    with _loop_lock:
        _loop_running = False
