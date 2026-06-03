"""
system_routes.py - Flask blueprint for system / status / clarifier / proposals endpoints.

Extracted from app.py during the Task 2 blueprint split. Behavior is byte-for-byte
identical to the original handlers; only the decorator changed from @app.route
to @system_bp.route.

Routes:
  /reflect                       POST  - run reflection cycle
  /daily_plan                    GET   - top-5 pending goals
  /heartbeat                     GET   - rolling status pulse
  /suggestions                   GET   - aggregated suggestions
  /personality                   GET   - personality status
  /provider_health               GET   - LLM provider health
  /proposals                     GET   - list proposals
  /proposals/<id>/approve        POST  - approve a proposal
  /proposals/<id>/apply          POST  - apply a proposal
  /status                        GET   - full agent status
  /clarify/check                 POST  - clarification gate
  /clarify/execute               POST  - run after user picks source
  /clarify/sources               GET   - source catalog

`get_mode` and `get_current_tier` live in app.py — they're imported lazily
inside the handlers that need them to avoid the circular import that would
otherwise occur during app.register_blueprint().
"""

import datetime
from flask import Blueprint, request, jsonify

import config as cfg
from config import AGENT_NAME

from reflection import run_reflection
from system_monitor import (
    pop_alerts, get_heartbeat_suggestions, get_system_health_score,
    load_proposals, save_proposals, apply_proposal,
)
from autonomous_loop import is_loop_running, pop_agent_suggestions
from personality import get_personality_status, get_mood, get_mood_icon
from llm_engine import get_provider_health, get_current_provider, determine_best_provider
from task_orchestrator import orchestrate
from smart_clarifier import check_clarification, execute_with_choice, get_all_sources

try:
    from intelligence_core import get_intelligence_status
    INTELLIGENCE_AVAILABLE = True
except ImportError:
    INTELLIGENCE_AVAILABLE = False
    def get_intelligence_status(): return {"status": "not loaded"}


system_bp = Blueprint("system", __name__)


# =============================================================================
# REFLECTION & PLANNING
# =============================================================================

@system_bp.route("/reflect", methods=["POST"])
def reflect_endpoint():
    result = run_reflection()
    return jsonify({
        "ok":        True,
        "metrics":   result.get("metrics", {}),
        "gaps":      result.get("gaps", []),
        "proposals": result.get("proposals", []),
    })


@system_bp.route("/daily_plan", methods=["GET"])
def daily_plan():
    from decision_engine import load_goals, GoalStatus
    goals   = load_goals()
    pending = [g for g in goals if g["status"] in (GoalStatus.PENDING, GoalStatus.BLOCKED)]
    pending.sort(key=lambda g: -g.get("urgency_score", 0))
    return jsonify({
        "date":    datetime.datetime.now().strftime("%Y-%m-%d"),
        "pending": pending[:5],
        "plan_created_at": datetime.datetime.now().isoformat(),
    })


# =============================================================================
# SYSTEM / STATUS
# =============================================================================

@system_bp.route("/heartbeat", methods=["GET"])
def heartbeat():
    from app import get_mode, get_current_tier
    alerts      = pop_alerts()
    suggestions = get_heartbeat_suggestions()
    agent_sug   = pop_agent_suggestions()
    ps          = get_personality_status()
    return jsonify({
        "ok":              True,
        "time":            datetime.datetime.now().strftime("%H:%M:%S"),
        "mode":            get_mode(),
        "tier":            get_current_tier(),
        "provider":        get_current_provider(),
        "mood":            ps.get("mood", "IDLE"),
        "mood_icon":       ps.get("mood_icon", "👁️"),
        "energy":          ps.get("energy_level", 1.0),
        "health_score":    get_system_health_score(),
        "loop_running":    is_loop_running(),
        "alerts":          alerts,
        "suggestions":     suggestions + agent_sug,
        "loop_running":    is_loop_running(),
    })


@system_bp.route("/suggestions", methods=["GET"])
def suggestions():
    return jsonify({
        "suggestions": get_heartbeat_suggestions() + pop_agent_suggestions(),
        "mood":        get_mood(),
        "mood_icon":   get_mood_icon(),
    })


@system_bp.route("/personality", methods=["GET"])
def personality_endpoint():
    return jsonify(get_personality_status())


@system_bp.route("/provider_health", methods=["GET"])
def provider_health_endpoint():
    health = get_provider_health()
    try:
        best = determine_best_provider("general query")
        health["_recommended"] = best
    except Exception:
        pass
    return jsonify(health)


# =============================================================================
# PROPOSALS
# =============================================================================

@system_bp.route("/proposals", methods=["GET"])
def list_proposals():
    """Phase 8.4 — list with optional ?status=pending filter."""
    proposals = load_proposals()
    status_filter = request.args.get("status")
    if status_filter:
        proposals = [p for p in proposals if p.get("status") == status_filter]
    return jsonify({
        "proposals": proposals,
        "count":     len(proposals),
    })


@system_bp.route("/proposals/<int:pid>/approve", methods=["POST"])
def approve_proposal(pid):
    """Mark a proposal `approved`. Does NOT modify code -- approving is
    bookkeeping; the destructive step is /proposals/<id>/apply which
    requires the Phase 7.3 confirm token."""
    proposals = load_proposals()
    found = False
    for p in proposals:
        if p["id"] == pid:
            p["status"] = "approved"
            found = True
    save_proposals(proposals)
    if not found:
        return jsonify({"ok": False, "error": f"proposal {pid} not found"}), 404
    return jsonify({"ok": True, "next": f"POST /proposals/{pid}/apply with confirm token"})


@system_bp.route("/proposals/<int:pid>/reject", methods=["POST"])
def reject_proposal(pid):
    """Phase 8.4 -- mark a proposal `rejected`. Idempotent + non-destructive."""
    proposals = load_proposals()
    found = False
    for p in proposals:
        if p["id"] == pid:
            p["status"] = "rejected"
            found = True
    save_proposals(proposals)
    if not found:
        return jsonify({"ok": False, "error": f"proposal {pid} not found"}), 404
    return jsonify({"ok": True})


@system_bp.route("/proposals/<int:pid>/apply", methods=["POST"])
def apply_proposal_route(pid):
    """Phase 8.4 — apply a previously-approved proposal. Behind the
    Phase 7.3 confirm gate because this can rewrite source files.

    Body: {"confirm": "I CONFIRM proposal_apply"}
    Returns 428 without the confirm; 409 if proposal isn't approved yet.
    """
    from confirm_gate import require_confirm
    denial = require_confirm("proposal_apply")
    if denial:
        return denial

    proposals = load_proposals()
    prop = next((p for p in proposals if p["id"] == pid), None)
    if not prop:
        return jsonify({"ok": False, "error": f"proposal {pid} not found"}), 404
    if prop.get("status") != "approved":
        return jsonify({
            "ok": False,
            "error": f"proposal {pid} status is {prop.get('status')!r}; "
                     "must be 'approved' before apply",
        }), 409

    result = apply_proposal(pid)
    return jsonify(result)


# =============================================================================
# AGENT STATUS
# =============================================================================

@system_bp.route("/status", methods=["GET"])
def status():
    from app import get_mode, get_current_tier
    ps = get_personality_status()
    return jsonify({
        "agent":        AGENT_NAME,
        "version":      cfg.AGENT_VERSION,
        "mode":         get_mode(),
        "tier":         get_current_tier(),
        "provider":     get_current_provider(),
        "mood":         ps.get("mood"),
        "mood_icon":    ps.get("mood_icon"),
        "energy":       ps.get("energy_level"),
        "loop_running": is_loop_running(),
        "health_score": get_system_health_score(),
        "time":         datetime.datetime.now().strftime("%H:%M:%S"),
        "date":         datetime.datetime.now().strftime("%Y-%m-%d"),
        "intelligence": get_intelligence_status() if INTELLIGENCE_AVAILABLE else {"status": "not loaded"},
    })


# =============================================================================
# SMART CLARIFIER ROUTES — /clarify/*
# Called by the UI BEFORE sending to /ask
# =============================================================================

@system_bp.route("/clarify/check", methods=["POST"])
def clarify_check():
    """
    Check if a query needs clarification before acting.
    Returns clarification options OR orchestrator result.
    Called by UI on every message FIRST.
    """
    data       = request.json or {}
    query      = (data.get("query") or "").strip()
    session_id = data.get("session_id", "default")

    if not query:
        return jsonify({"needs_clarification": False})

    # 1. Check orchestrator first (immediate actions: screenshot, folder, etc.)
    orch = orchestrate(query, session_id=session_id)
    if orch.get("action_taken") and not orch.get("passthrough"):
        return jsonify({
            "needs_clarification": False,
            "action_taken":        orch.get("action_taken"),
            "message":             orch.get("message"),
            "needs_input":         orch.get("needs_input", False),
            "questions":           orch.get("questions", []),
            "data":                orch,
        })

    # 2. Check if clarification is needed
    clarification = check_clarification(query)
    if clarification:
        return jsonify({
            "needs_clarification": True,
            "question":   clarification["question"],
            "options":    clarification["options"],
            "flow":       clarification["flow"],
            "query":      query,
        })

    # 3. No clarification needed - let normal AI handle it
    return jsonify({"needs_clarification": False, "passthrough": True})


@system_bp.route("/clarify/execute", methods=["POST"])
def clarify_execute():
    """
    After user picks a source, open it.
    Body: {query, source_key, session_id}
    """
    data       = request.json or {}
    query      = data.get("query", "").strip()
    source_key = data.get("source_key", "google")
    session_id = data.get("session_id", "default")

    if not query:
        return jsonify({"error": "query required"}), 400

    result = execute_with_choice(query, source_key)
    return jsonify(result)


@system_bp.route("/clarify/sources", methods=["GET"])
def clarify_sources():
    """Return all available sources catalog."""
    return jsonify(get_all_sources())


@system_bp.route("/system/activity", methods=["GET"])
def system_activity():
    """Return current mouse/keyboard activity state."""
    try:
        from activity_tracker import get_activity
        return jsonify(get_activity())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@system_bp.route("/system/error_scores", methods=["GET"])
def system_error_scores():
    """Return per-module failure counts from the last 24 hours."""
    try:
        from error_tracker import get_module_scores, get_top_problem_module
        return jsonify({
            "scores": get_module_scores(),
            "top":    get_top_problem_module(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
