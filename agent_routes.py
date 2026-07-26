"""
agent_routes.py — Flask Blueprint for Ultron-J's autonomous agent system. ULTIMATE.

NEW ENDPOINTS vs previous version:
/agent/personality          - mood status, energy level
/agent/personality/mood     - set mood manually
/agent/perception           - what Ultron currently sees
/agent/perception/clipboard - current clipboard content
/agent/reflection           - self-reflection log
/agent/reflection/run       - trigger a reflection cycle now
/agent/notes                - list and search notes
/agent/notes/create         - create a note
/agent/network              - connectivity status
/agent/health               - overall system health score
/agent/entity/<name>        - get entity graph context
/agent/search               - fuzzy search across all memory layers
/agent/calculate            - safe math evaluation
/agent/code                 - run code in sandbox
/agent/weather              - fetch weather
/agent/vision               - analyze image URL
"""

import datetime
import json
from flask import Blueprint, request, jsonify

from decision_engine import (
    create_goal, get_goal, get_all_goals, delete_goal,
    update_goal, get_active_goals, get_next_goal,
    load_working_memory, get_execution_log,
    load_agent_state, Priority, GoalStatus,
    create_goal_from_template,
)
from action_engine import (
    get_knowledge_stats, recall_knowledge, store_knowledge,
    load_tool_stats, execute_action, fetch_weather,
    run_code_sandbox, safe_calculate, search_notes, create_note,
)
from autonomous_loop import (
    start_autonomous_loop, stop_autonomous_loop, is_loop_running,
    load_loop_status, get_self_improvement_log,
    pop_agent_suggestions, observe_environment,
    parse_goal_from_text, push_agent_suggestion, is_online,
)

try:
    from system_monitor import (
        push_alert, get_system_health_score,
        get_cpu_usage, get_memory_usage, get_battery_status,
        get_disk_usage, get_ollama_models, get_dev_processes,
    )
except ImportError:
    def push_alert(msg): print(f"[ALERT] {msg}")
    def get_system_health_score(): return 100
    def get_cpu_usage(): return {}
    def get_memory_usage(): return {}
    def get_battery_status(): return {}
    def get_disk_usage(): return {}
    def get_ollama_models(): return []
    def get_dev_processes(): return []

try:
    from personality import (
        get_personality_status, set_mood, get_mood, EMOTION_STATES,
    )
except ImportError:
    def get_personality_status(): return {}
    def set_mood(m, r=""): pass
    def get_mood(): return "IDLE"
    EMOTION_STATES = {}

try:
    from perception import (
        get_perception_state, get_recent_perceptions,
        get_clipboard_content, build_perception_context,
    )
except ImportError:
    def get_perception_state(): return {}
    def get_recent_perceptions(n=5): return []
    def get_clipboard_content(): return ""
    def build_perception_context(): return ""

try:
    from reflection import (
        run_reflection, get_recent_reflections, get_reflection_summary,
        should_reflect,
    )
except ImportError:
    def run_reflection(): return {}
    def get_recent_reflections(n=5, kind=""): return []
    def get_reflection_summary(): return ""
    def should_reflect(): return False

try:
    from memory import (
        fuzzy_recall, get_top_entities, get_entity_context,
        upsert_entity, get_episode_stats,
    )
except ImportError:
    def fuzzy_recall(q, n=5): return {}
    def get_top_entities(n=10, kind=""): return []
    def get_entity_context(name): return ""
    def upsert_entity(**kwargs): pass
    def get_episode_stats(): return {}

try:
    from llm_engine import call_llm_vision, get_provider_health
except ImportError:
    def call_llm_vision(url, prompt): return "Vision unavailable"
    def get_provider_health(): return {}

agent_bp = Blueprint("agent", __name__, url_prefix="/agent")

# =============================================================================
# GOALS
# =============================================================================

@agent_bp.route("/goals", methods=["GET"])
def list_goals():
    goals         = get_all_goals()
    status_filter = request.args.get("status")
    if status_filter:
        goals = [g for g in goals if g["status"] == status_filter]
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    goals.sort(key=lambda g: (
        0 if g["status"] in ("active", "executing") else
        1 if g["status"] == "pending" else 2,
        priority_order.get(g.get("priority", "medium"), 2),
        -g.get("urgency_score", 0),
    ))
    return jsonify({
        "goals":     goals,
        "total":     len(goals),
        "pending":   len([g for g in goals if g["status"] == GoalStatus.PENDING]),
        "active":    len([g for g in goals if g["status"] in (GoalStatus.ACTIVE, GoalStatus.EXECUTING)]),
        "completed": len([g for g in goals if g["status"] == GoalStatus.COMPLETED]),
        "failed":    len([g for g in goals if g["status"] == GoalStatus.FAILED]),
    })


@agent_bp.route("/goals", methods=["POST"])
def create_goal_route():
    data     = request.json or {}
    title    = data.get("title", "").strip()
    desc     = data.get("description", "").strip()
    priority = data.get("priority", Priority.MEDIUM)
    tags     = data.get("tags", [])
    depends  = data.get("depends_on", [])
    criteria = data.get("success_criteria", "")
    template = data.get("template", "")

    if not title:
        return jsonify({"ok": False, "msg": "Title required"}), 400
    if not desc:
        desc = title

    if template:
        goal = create_goal_from_template(template, topic=title, filename=title)
        if not goal:
            goal = create_goal(title=title, description=desc, priority=priority,
                               source="user", tags=tags, depends_on=depends,
                               success_criteria=criteria)
    else:
        goal = create_goal(title=title, description=desc, priority=priority,
                           source="user", tags=tags, depends_on=depends,
                           success_criteria=criteria)

    push_alert(f"🎯 New goal: {title}")
    push_agent_suggestion(f"🎯 Goal queued: '{title}' — I'll get to it.")
    return jsonify({"ok": True, "goal": goal})


@agent_bp.route("/goals/<goal_id>", methods=["GET"])
def get_goal_route(goal_id):
    goal = get_goal(goal_id)
    if not goal:
        return jsonify({"ok": False, "msg": "Goal not found"}), 404
    return jsonify(goal)


@agent_bp.route("/goals/<goal_id>", methods=["DELETE"])
def delete_goal_route(goal_id):
    delete_goal(goal_id)
    return jsonify({"ok": True, "msg": f"Goal {goal_id} deleted"})


@agent_bp.route("/goals/<goal_id>/pause", methods=["POST"])
def pause_goal(goal_id):
    update_goal(goal_id, status=GoalStatus.PAUSED)
    return jsonify({"ok": True, "msg": "Goal paused"})


@agent_bp.route("/goals/<goal_id>/resume", methods=["POST"])
def resume_goal(goal_id):
    update_goal(goal_id, status=GoalStatus.PENDING)
    return jsonify({"ok": True, "msg": "Goal resumed"})


# ── Phase 14: self-authored goal proposals awaiting approval ──────────────────
@agent_bp.route("/proposals", methods=["GET"])
def list_proposals():
    """Proposals Ultron authored for itself that are parked for approval."""
    try:
        import goal_author
        pending = goal_author.list_pending()
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e), "proposals": []}), 200
    return jsonify({"ok": True, "proposals": pending, "total": len(pending)})


@agent_bp.route("/proposals/<path:dedup_key>/approve", methods=["POST"])
def approve_proposal(dedup_key):
    """Approve a parked proposal -> create the real goal."""
    try:
        import goal_author
        goal = goal_author.approve(dedup_key)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 200
    if goal is None:
        return jsonify({"ok": False, "msg": "No such proposal"}), 404
    return jsonify({"ok": True, "goal": goal})


@agent_bp.route("/proposals/<path:dedup_key>/reject", methods=["POST"])
def reject_proposal(dedup_key):
    """Drop a parked proposal without creating a goal."""
    try:
        import goal_author
        removed = goal_author.reject(dedup_key)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 200
    return jsonify({"ok": bool(removed),
                    "msg": "Rejected" if removed else "No such proposal"})


# ── Phase 23: approval-gated self-modification ────────────────────────────────
# The queue Ultron writes to when it wants to change its own code. Built and
# tested in Phase 23 but never given a human surface, which made an
# "approval-gated" feature unreachable by the approver.
#
# SAFETY INVARIANT: nothing here applies a patch except an explicit POST to
# .../approve. Listing, reading and the ledger are read-only, and staging a
# proposal never applies it. Ungated by flag for the same reason the Phase 15
# proposal routes are — a review surface you have to enable is a review surface
# nobody uses; the gate is the human, not the env var.
@agent_bp.route("/self_modify/proposals", methods=["GET"])
def list_self_modify_proposals():
    """Self-modifications staged for human review. Read-only."""
    try:
        import self_modify_proposals
        pending = self_modify_proposals.list_pending()
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e), "proposals": []}), 200
    return jsonify({"ok": True, "proposals": pending, "total": len(pending)})


@agent_bp.route("/self_modify/proposals", methods=["POST"])
def stage_self_modify_proposal():
    """Stage a patch for review. Validates target + syntax; does NOT apply."""
    data = request.json or {}
    filename = (data.get("filename") or "").strip()
    new_code = data.get("new_code") or ""
    if not filename or not new_code:
        return jsonify({"ok": False, "msg": "filename and new_code are required"}), 400
    try:
        import self_modify_proposals
        result = self_modify_proposals.propose(
            filename, new_code,
            request=data.get("request", ""), rationale=data.get("rationale", ""))
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 200
    if not result.get("ok"):
        return jsonify({"ok": False, "msg": result.get("error", "rejected")}), 200
    return jsonify(result)


@agent_bp.route("/self_modify/proposals/<proposal_id>", methods=["GET"])
def get_self_modify_proposal(proposal_id):
    """Full detail of one proposal, including the patch body. Read-only."""
    try:
        import self_modify_proposals
        entry = self_modify_proposals.get(proposal_id)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 200
    if entry is None:
        return jsonify({"ok": False, "msg": "No such proposal"}), 404
    return jsonify({"ok": True, "proposal": entry})


@agent_bp.route("/self_modify/proposals/<proposal_id>/approve", methods=["POST"])
def approve_self_modify_proposal(proposal_id):
    """THE ONLY PATH THAT WRITES CODE. Requires a deliberate human POST."""
    try:
        import self_modify_proposals
        result = self_modify_proposals.approve(proposal_id)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 200
    if not result.get("ok"):
        err = result.get("error", "approve failed")
        code = 404 if "no such proposal" in err.lower() else 200
        return jsonify({"ok": False, "msg": err}), code
    return jsonify(result)


@agent_bp.route("/self_modify/proposals/<proposal_id>/reject", methods=["POST"])
def reject_self_modify_proposal(proposal_id):
    """Drop a staged patch without applying it."""
    try:
        import self_modify_proposals
        removed = self_modify_proposals.reject(proposal_id)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 200
    if not removed:
        return jsonify({"ok": False, "msg": "No such pending proposal"}), 404
    return jsonify({"ok": True, "msg": "Rejected"})


@agent_bp.route("/self_modify/proposals/<proposal_id>/rollback", methods=["POST"])
def rollback_self_modify_proposal(proposal_id):
    """Undo an applied patch from its backup."""
    try:
        import self_modify_proposals
        result = self_modify_proposals.rollback(proposal_id)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 200
    if not result.get("ok"):
        err = result.get("error", "rollback failed")
        code = 404 if "no applied proposal" in err.lower() else 200
        return jsonify({"ok": False, "msg": err}), code
    return jsonify(result)


@agent_bp.route("/self_modify/ledger", methods=["GET"])
def self_modify_ledger():
    """Append-only history of every propose/apply/reject/rollback. Read-only."""
    try:
        import self_modify_proposals
        entries = self_modify_proposals.get_ledger()
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e), "ledger": []}), 200
    return jsonify({"ok": True, "ledger": entries, "total": len(entries)})


@agent_bp.route("/goals/from_text", methods=["POST"])
def goal_from_text():
    data = request.json or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"ok": False, "msg": "No text provided"}), 400
    parsed = parse_goal_from_text(text)
    if parsed:
        template = parsed.pop("template", None)
        if template:
            goal = create_goal_from_template(template, topic=parsed["title"])
        else:
            goal = create_goal(**parsed, source="user_text")
        return jsonify({"ok": True, "goal": goal, "parsed": True})
    goal = create_goal(title=text[:60], description=text, source="user_text")
    return jsonify({"ok": True, "goal": goal, "parsed": False})


@agent_bp.route("/goals/template", methods=["POST"])
def create_from_template():
    data     = request.json or {}
    template = data.get("template", "")
    kwargs   = {k: v for k, v in data.items() if k != "template"}
    goal = create_goal_from_template(template, **kwargs)
    if not goal:
        return jsonify({"ok": False, "msg": f"Template '{template}' not found"}), 404
    return jsonify({"ok": True, "goal": goal})

# =============================================================================
# LOOP CONTROL
# =============================================================================

@agent_bp.route("/loop/start", methods=["POST"])
def start_loop():
    if is_loop_running():
        return jsonify({"ok": True, "msg": "Loop already running", "running": True})
    started = start_autonomous_loop()
    return jsonify({"ok": started, "msg": "Autonomous loop started", "running": True})


@agent_bp.route("/loop/stop", methods=["POST"])
def stop_loop():
    stop_autonomous_loop()
    return jsonify({"ok": True, "msg": "Loop stopped", "running": False})


@agent_bp.route("/loop/status", methods=["GET"])
def loop_status():
    status = load_loop_status()
    state  = load_agent_state()
    return jsonify({**status, "agent_state": state, "online": is_online()})

# =============================================================================
# PERSONALITY (NEW)
# =============================================================================

@agent_bp.route("/personality", methods=["GET"])
def personality_status():
    return jsonify(get_personality_status())


@agent_bp.route("/personality/mood", methods=["POST"])
def set_mood_route():
    data    = request.json or {}
    mood    = data.get("mood", "").upper()
    reason  = data.get("reason", "manual override")
    if mood not in EMOTION_STATES:
        return jsonify({"ok": False, "msg": f"Unknown mood. Valid: {list(EMOTION_STATES.keys())}"}), 400
    set_mood(mood, reason)
    return jsonify({"ok": True, "mood": mood, "msg": f"Mood set to {mood}"})

# =============================================================================
# PERCEPTION (NEW)
# =============================================================================

@agent_bp.route("/perception", methods=["GET"])
def perception_status():
    return jsonify(get_perception_state())


@agent_bp.route("/perception/recent", methods=["GET"])
def recent_perceptions():
    n = int(request.args.get("n", 10))
    return jsonify({"perceptions": get_recent_perceptions(n)})


@agent_bp.route("/perception/clipboard", methods=["GET"])
def clipboard_status():
    content = get_clipboard_content()
    return jsonify({
        "has_content": bool(content),
        "length":      len(content),
        "preview":     content[:200] if content else "",
    })


@agent_bp.route("/perception/context", methods=["GET"])
def perception_context():
    ctx = build_perception_context()
    return jsonify({"context": ctx})

# =============================================================================
# REFLECTION (NEW)
# =============================================================================

@agent_bp.route("/reflection", methods=["GET"])
def reflection_log():
    n    = int(request.args.get("n", 10))
    kind = request.args.get("kind", "")
    return jsonify({
        "reflections": get_recent_reflections(n, kind),
        "summary":     get_reflection_summary(),
        "should_reflect": should_reflect(),
    })


@agent_bp.route("/reflection/run", methods=["POST"])
def trigger_reflection():
    result = run_reflection()
    return jsonify({
        "ok":        True,
        "metrics":   result.get("metrics", {}),
        "gaps":      result.get("gaps", []),
        "proposals": result.get("proposals", []),
    })

# =============================================================================
# MEMORY / KNOWLEDGE
# =============================================================================

@agent_bp.route("/memory", methods=["GET"])
def working_memory():
    return jsonify(load_working_memory())


@agent_bp.route("/knowledge", methods=["GET"])
def knowledge_stats():
    return jsonify(get_knowledge_stats())


@agent_bp.route("/knowledge/search", methods=["POST"])
def search_knowledge():
    data  = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"ok": False, "msg": "Query required"}), 400
    entries = recall_knowledge(query, n=10)
    return jsonify({"ok": True, "results": entries, "count": len(entries)})


@agent_bp.route("/knowledge/store", methods=["POST"])
def store_knowledge_route():
    data    = request.json or {}
    topic   = data.get("topic", "general")
    content = data.get("content", "")
    if not content:
        return jsonify({"ok": False, "msg": "Content required"}), 400
    store_knowledge(topic, content, source="user")
    return jsonify({"ok": True, "msg": f"Stored under topic '{topic}'"})


@agent_bp.route("/memory/search", methods=["POST"])
def fuzzy_memory_search():
    """Search across ALL memory layers simultaneously."""
    data  = request.json or {}
    query = data.get("query", "").strip()
    n     = int(data.get("n", 5))
    if not query:
        return jsonify({"ok": False, "msg": "Query required"}), 400
    results = fuzzy_recall(query, n=n)
    return jsonify({"ok": True, "query": query, "results": results})


@agent_bp.route("/episodes", methods=["GET"])
def episode_stats():
    return jsonify(get_episode_stats())

# =============================================================================
# ENTITY GRAPH (NEW)
# =============================================================================

@agent_bp.route("/entity/<name>", methods=["GET"])
def entity_info(name):
    ctx = get_entity_context(name)
    return jsonify({"entity": name, "context": ctx})


@agent_bp.route("/entities/top", methods=["GET"])
def top_entities():
    n    = int(request.args.get("n", 10))
    kind = request.args.get("kind", "")
    return jsonify({"entities": get_top_entities(n=n, kind=kind)})

# =============================================================================
# TOOLS
# =============================================================================

@agent_bp.route("/tools", methods=["GET"])
def tool_stats():
    return jsonify(load_tool_stats())


@agent_bp.route("/tools/execute", methods=["POST"])
def execute_tool():
    data        = request.json or {}
    action_type = data.get("action", "")
    params      = data.get("params", {})
    if not action_type:
        return jsonify({"ok": False, "msg": "Action type required"}), 400
    result = execute_action(action_type, params)
    return jsonify({"ok": result.get("success", False), "result": result})

# =============================================================================
# NEW CAPABILITY ENDPOINTS
# =============================================================================

@agent_bp.route("/calculate", methods=["POST"])
def calculate():
    data = request.json or {}
    expr = data.get("expression", "").strip()
    if not expr:
        return jsonify({"ok": False, "msg": "Expression required"}), 400
    result = safe_calculate(expr)
    return jsonify(result)


@agent_bp.route("/code", methods=["POST"])
def run_code():
    data    = request.json or {}
    code    = data.get("code", "").strip()
    timeout = int(data.get("timeout", 10))
    if not code:
        return jsonify({"ok": False, "msg": "Code required"}), 400
    result = run_code_sandbox(code, timeout=timeout)
    return jsonify(result)


@agent_bp.route("/weather", methods=["GET"])
def weather():
    location = request.args.get("location", "")
    result   = fetch_weather(location or None)
    return jsonify(result)


@agent_bp.route("/vision", methods=["POST"])
def vision_analyze():
    data   = request.json or {}
    url    = data.get("image_url", "")
    prompt = data.get("prompt", "Describe this image in detail.")
    if not url:
        return jsonify({"ok": False, "msg": "image_url required"}), 400
    result = call_llm_vision(url, prompt)
    return jsonify({"ok": True, "result": result})

# =============================================================================
# NOTES (NEW)
# =============================================================================

@agent_bp.route("/notes", methods=["GET"])
def list_notes():
    query = request.args.get("q", "")
    if query:
        notes = search_notes(query)
    else:
        from action_engine import load_notes
        notes = load_notes()[-20:]
    return jsonify({"notes": notes, "count": len(notes)})


@agent_bp.route("/notes/create", methods=["POST"])
def create_note_route():
    data    = request.json or {}
    title   = data.get("title", "Untitled")
    content = data.get("content", "")
    cat     = data.get("category", "general")
    tags    = data.get("tags", [])
    if not content:
        return jsonify({"ok": False, "msg": "Content required"}), 400
    note = create_note(title, content, cat, tags)
    return jsonify({"ok": True, "note": note})

# =============================================================================
# SYSTEM HEALTH (NEW)
# =============================================================================

@agent_bp.route("/health", methods=["GET"])
def system_health():
    return jsonify({
        "health_score":   get_system_health_score(),
        "memory":         get_memory_usage(),
        "cpu":            get_cpu_usage(),
        "battery":        get_battery_status(),
        "disk":           get_disk_usage(),
        "ollama_models":  get_ollama_models(),
        "dev_processes":  get_dev_processes()[:5],
        "online":         is_online(),
        "provider_health": get_provider_health(),
    })


@agent_bp.route("/network", methods=["GET"])
def network_status():
    return jsonify({
        "online": is_online(),
        "checked_at": datetime.datetime.now().isoformat(),
    })



# =============================================================================
# SELF-IMPROVEMENT + EXECUTION LOG
# =============================================================================

@agent_bp.route("/self_improve", methods=["GET"])
def self_improve_log():
    log = get_self_improvement_log()
    return jsonify({"log": log[-20:], "total": len(log)})


@agent_bp.route("/execution_log", methods=["GET"])
def execution_log():
    n   = int(request.args.get("n", 20))
    log = get_execution_log(n)
    return jsonify({"log": log, "count": len(log)})


@agent_bp.route("/suggestions", methods=["GET"])
def agent_suggestions():
    suggestions = pop_agent_suggestions()
    return jsonify({"suggestions": suggestions, "count": len(suggestions)})


@agent_bp.route("/state", methods=["GET"])
def agent_state():
    return jsonify({
        "agent_state":   load_agent_state(),
        "working_memory": load_working_memory(),
        "loop":          load_loop_status(),
        "personality":   get_personality_status(),
        "health_score":  get_system_health_score(),
        "online":        is_online(),
    })

# =============================================================================
# VOICE AGENT ROUTES — /agent/voice/*
# =============================================================================

try:
    from voice_engine import (
        tts as _voice_tts,
        stt as _voice_stt,
        get_voice_status as _voice_status,
        get_voice_log as _voice_log,
        parse_voice_command as _parse_cmd,
        execute_voice_command as _exec_cmd,
        generate_voice_briefing as _voice_briefing,
    )
    _VOICE_ROUTES_AVAILABLE = True
except ImportError:
    _VOICE_ROUTES_AVAILABLE = False


@agent_bp.route("/voice/status", methods=["GET"])
def agent_voice_status():
    """Current voice engine capabilities."""
    if not _VOICE_ROUTES_AVAILABLE:
        return jsonify({"ready": False, "error": "pip install edge-tts"})
    return jsonify(_voice_status())


@agent_bp.route("/voice/speak", methods=["POST"])
def agent_voice_speak():
    """
    POST /agent/voice/speak
    Body: {"text": "...", "mood": "FOCUSED"}
    Returns: MP3 audio
    """
    from flask import Response as _Resp
    if not _VOICE_ROUTES_AVAILABLE:
        return jsonify({"error": "Voice not available"}), 503
    data  = request.json or {}
    text  = data.get("text", "").strip()
    mood  = data.get("mood", "FOCUSED")
    if not text:
        return jsonify({"error": "text required"}), 400
    try:
        audio, prov = _voice_tts(text, mood=mood)
        return _Resp(audio, mimetype="audio/mpeg",
                     headers={"X-Mood": mood, "X-Provider": prov,
                              "Access-Control-Expose-Headers": "X-Mood,X-Provider"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@agent_bp.route("/voice/transcribe", methods=["POST"])
def agent_voice_transcribe():
    """
    POST /agent/voice/transcribe
    Body: multipart/form-data with 'audio' field
    Returns: {"text": "...", "confidence": 0.9, "provider": "..."}
    """
    if not _VOICE_ROUTES_AVAILABLE:
        return jsonify({"error": "Voice not available"}), 503
    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400
    audio_bytes = request.files["audio"].read()
    return jsonify(_voice_stt(audio_bytes))


@agent_bp.route("/voice/log", methods=["GET"])
def agent_voice_log():
    """Recent voice interaction history."""
    if not _VOICE_ROUTES_AVAILABLE:
        return jsonify({"log": [], "ready": False})
    n = int(request.args.get("n", 20))
    return jsonify({"log": _voice_log(n), "count": n, "ready": True})


@agent_bp.route("/voice/briefing", methods=["GET"])
def agent_voice_briefing():
    """
    GET /agent/voice/briefing?kind=morning
    Returns MP3 audio briefing.
    """
    from flask import Response as _Resp
    if not _VOICE_ROUTES_AVAILABLE:
        return jsonify({"error": "Voice not available"}), 503
    kind = request.args.get("kind", "morning")
    try:
        mood = get_mood()
        text = _voice_briefing(kind)
        audio, prov = _voice_tts(text, mood=mood)
        return _Resp(audio, mimetype="audio/mpeg",
                     headers={"X-Briefing-Text": text[:300], "X-Mood": mood,
                              "Access-Control-Expose-Headers": "X-Briefing-Text,X-Mood"})
    except Exception as e:
        # A missing optional dependency (edge-tts) or unavailable audio
        # device is a degraded-mode 503, not a 500 crash.
        from optional_feature import http_status_for
        return jsonify({"error": str(e)}), http_status_for(e)

# =============================================================================
# COMPUTER CONTROL ROUTES — /agent/computer/*
# =============================================================================

try:
    from computer_control import (
        execute_computer_action as _cc_action,
        get_computer_status    as _cc_status,
        get_action_log         as _cc_log,
        take_screenshot        as _cc_screenshot,
        send_email             as _cc_email,
    )
    _CC_AVAILABLE = True
except ImportError:
    _CC_AVAILABLE = False


@agent_bp.route("/computer/status", methods=["GET"])
def agent_computer_status():
    if not _CC_AVAILABLE:
        return jsonify({"available": False, "error": "pip install pyautogui pillow"})
    return jsonify({**_cc_status(), "available": True})


@agent_bp.route("/computer/action", methods=["POST"])
def agent_computer_action():
    """POST body: {"action": "click|type|screenshot|open_url|...", "params": {...}}"""
    if not _CC_AVAILABLE:
        return jsonify({"success": False, "error": "pip install pyautogui pillow"}), 503
    data   = request.json or {}
    action = data.get("action", "").strip()
    params = data.get("params", {})
    if not action:
        return jsonify({"success": False, "error": "action required"}), 400
    return jsonify(_cc_action(action, params))


@agent_bp.route("/computer/screenshot", methods=["GET"])
def agent_computer_screenshot():
    if not _CC_AVAILABLE:
        return jsonify({"success": False, "error": "pip install pyautogui pillow"}), 503
    return jsonify(_cc_screenshot())


@agent_bp.route("/computer/log", methods=["GET"])
def agent_computer_log():
    if not _CC_AVAILABLE:
        return jsonify({"log": [], "available": False})
    n = int(request.args.get("n", 20))
    return jsonify({"log": _cc_log(n), "available": True})


@agent_bp.route("/computer/email", methods=["POST"])
def agent_computer_email():
    """POST body: {"to": "...", "subject": "...", "body": "..."}"""
    if not _CC_AVAILABLE:
        return jsonify({"success": False, "error": "computer_control not available"}), 503
    data = request.json or {}
    to      = data.get("to", "").strip()
    subject = data.get("subject", "").strip()
    body    = data.get("body", "").strip()
    if not all([to, subject, body]):
        return jsonify({"success": False, "error": "to, subject, body required"}), 400
    return jsonify(_cc_email(to, subject, body))
