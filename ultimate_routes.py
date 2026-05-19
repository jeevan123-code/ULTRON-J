"""
ultimate_routes.py — Flask blueprint exposing the new Ultron-J upgrades.

Registered from app.py with:
    from ultimate_routes import ultimate_bp, start_ultimate_loops
    app.register_blueprint(ultimate_bp)
    start_ultimate_loops()   # starts distiller + evolution + proactive planner

All routes are prefixed /ultimate so they don't clash with the existing ~200
routes already in app.py. Any module that's missing degrades gracefully — the
corresponding route just returns {"available": false, ...}.

Route map:
  Vector store          /ultimate/vector/{stats,recall,remember,forget}
  Research              /ultimate/research          POST {question, depth}
  Orchestrator / DAG    /ultimate/orchestrate       POST {request}
                        /ultimate/graphs, /ultimate/graphs/<id>
  Model selector        /ultimate/selector/{status,override}
  Distiller             /ultimate/distiller/{status,run,lessons,start,stop}
  Evolution             /ultimate/evolution/{status,run,log,start,stop}
  Proactive planner     /ultimate/proactive/{status,run,pending,mark,start,stop}
  Tweak engine          /ultimate/tweak/{list,apply,rollback,log,backups}
  Master status         /ultimate/status
"""

import json
from typing import Dict
from flask import Blueprint, request, jsonify

ultimate_bp = Blueprint("ultimate", __name__, url_prefix="/ultimate")


# ============================================================================
# Safe-import everything — any module can be missing without breaking others
# ============================================================================

def _safe_import(name):
    try:
        return __import__(name)
    except Exception as e:
        print(f"[ultimate_routes] module {name} not importable: {e}")
        return None


vector_store       = _safe_import("vector_store")
research_engine    = _safe_import("research_engine")
brain_orchestrator = _safe_import("brain_orchestrator")
task_graph         = _safe_import("task_graph")
model_selector     = _safe_import("model_selector")
memory_distiller   = _safe_import("memory_distiller")
evolution_loop     = _safe_import("evolution_loop")
proactive_planner  = _safe_import("proactive_planner")
tweak_engine       = _safe_import("tweak_engine")
skill_learner      = _safe_import("skill_learner")
predictive_monitor = _safe_import("predictive_monitor")
human_interface    = _safe_import("human_interface")


def _json_ok(**kw):
    return jsonify({"success": True, **kw})


def _json_err(msg, code=400):
    return jsonify({"success": False, "error": msg}), code


def _unavailable(mod_name: str):
    return _json_err(f"{mod_name} module not available", 503)


# ============================================================================
# VECTOR STORE
# ============================================================================

@ultimate_bp.route("/vector/stats", methods=["GET"])
def vector_stats():
    if not vector_store:
        return _unavailable("vector_store")
    return jsonify(vector_store.stats())


@ultimate_bp.route("/vector/recall", methods=["POST"])
def vector_recall():
    if not vector_store:
        return _unavailable("vector_store")
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return _json_err("query required")
    n = int(data.get("n", 5))
    kind = data.get("kind") or None
    min_score = float(data.get("min_score", 0.0))
    hits = vector_store.recall(query, n=n, kind=kind, min_score=min_score)
    return _json_ok(hits=hits, count=len(hits))


@ultimate_bp.route("/vector/remember", methods=["POST"])
def vector_remember():
    if not vector_store:
        return _unavailable("vector_store")
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return _json_err("text required")
    kind = data.get("kind", "general")
    metadata = data.get("metadata") or {}
    doc_id = vector_store.remember(text, kind=kind, metadata=metadata)
    return _json_ok(id=doc_id, kind=kind)


@ultimate_bp.route("/vector/forget/<doc_id>", methods=["POST", "DELETE"])
def vector_forget(doc_id):
    if not vector_store:
        return _unavailable("vector_store")
    ok = vector_store.forget(doc_id)
    return _json_ok(deleted=ok, id=doc_id) if ok else _json_err("not found or delete failed", 404)


# ============================================================================
# RESEARCH (Claude-like search)
# ============================================================================

@ultimate_bp.route("/research", methods=["POST"])
def research_endpoint():
    if not research_engine:
        return _unavailable("research_engine")
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    if not question:
        return _json_err("question required")
    depth = data.get("depth", "standard")
    skip_cache = bool(data.get("skip_cache", False))
    if depth not in ("quick", "standard", "deep"):
        return _json_err("depth must be quick/standard/deep")
    try:
        result = research_engine.research(question, depth=depth, skip_cache=skip_cache)
        return jsonify({"success": True, **result})
    except Exception as e:
        return _json_err(f"research failed: {e}", 500)


# ============================================================================
# BRAIN ORCHESTRATOR (DAG planner)
# ============================================================================

@ultimate_bp.route("/orchestrate", methods=["POST"])
def orchestrate_endpoint():
    if not brain_orchestrator:
        return _unavailable("brain_orchestrator")
    data = request.get_json(silent=True) or {}
    req = data.get("request", "").strip()
    if not req:
        return _json_err("request required")
    context = data.get("context", "")
    try:
        result = brain_orchestrator.orchestrate(req, context=context)
        return jsonify({"success": True, **result})
    except Exception as e:
        return _json_err(f"orchestrate failed: {e}", 500)


@ultimate_bp.route("/graphs", methods=["GET"])
def graphs_list():
    if not task_graph:
        return _unavailable("task_graph")
    return _json_ok(graphs=task_graph.TaskGraph.list_all())


@ultimate_bp.route("/graphs/<graph_id>", methods=["GET"])
def graph_detail(graph_id):
    if not task_graph:
        return _unavailable("task_graph")
    g = task_graph.TaskGraph.load(graph_id)
    if not g:
        return _json_err("graph not found", 404)
    return _json_ok(summary=g.summary(), tasks=list(g.tasks.values()))


# ============================================================================
# MODEL SELECTOR
# ============================================================================

@ultimate_bp.route("/selector/status", methods=["GET"])
def selector_status():
    if not model_selector:
        return _unavailable("model_selector")
    return jsonify(model_selector.status())


@ultimate_bp.route("/selector/override", methods=["POST"])
def selector_override():
    if not model_selector:
        return _unavailable("model_selector")
    data = request.get_json(silent=True) or {}
    scope = data.get("scope", "global")  # "global" or "kind"
    provider = data.get("provider")  # str or None to clear
    if scope == "global":
        model_selector.set_global_override(provider)
    elif scope == "kind":
        kind = data.get("kind")
        if not kind:
            return _json_err("kind required when scope=kind")
        model_selector.set_kind_override(kind, provider)
    else:
        return _json_err("scope must be 'global' or 'kind'")
    return _json_ok(status=model_selector.status())


# ============================================================================
# MEMORY DISTILLER
# ============================================================================

@ultimate_bp.route("/distiller/status", methods=["GET"])
def distiller_status():
    if not memory_distiller:
        return _unavailable("memory_distiller")
    return jsonify(memory_distiller.get_distiller_status())


@ultimate_bp.route("/distiller/run", methods=["POST"])
def distiller_run():
    if not memory_distiller:
        return _unavailable("memory_distiller")
    return jsonify(memory_distiller.run_now())


@ultimate_bp.route("/distiller/lessons", methods=["GET"])
def distiller_lessons():
    if not memory_distiller:
        return _unavailable("memory_distiller")
    n = int(request.args.get("n", 20))
    category = request.args.get("category")
    return _json_ok(lessons=memory_distiller.get_lessons(n=n, category=category))


@ultimate_bp.route("/distiller/start", methods=["POST"])
def distiller_start():
    if not memory_distiller:
        return _unavailable("memory_distiller")
    data = request.get_json(silent=True) or {}
    hours = float(data.get("interval_hours", memory_distiller.DEFAULT_INTERVAL_HOURS))
    ok = memory_distiller.start_distiller(interval_hours=hours)
    return _json_ok(started=ok, interval_hours=hours)


@ultimate_bp.route("/distiller/stop", methods=["POST"])
def distiller_stop():
    if not memory_distiller:
        return _unavailable("memory_distiller")
    return _json_ok(stopped=memory_distiller.stop_distiller())


# ============================================================================
# EVOLUTION LOOP
# ============================================================================

@ultimate_bp.route("/evolution/status", methods=["GET"])
def evolution_status():
    if not evolution_loop:
        return _unavailable("evolution_loop")
    return jsonify(evolution_loop.get_evolution_status())


@ultimate_bp.route("/evolution/run", methods=["POST"])
def evolution_run():
    if not evolution_loop:
        return _unavailable("evolution_loop")
    return jsonify(evolution_loop.run_now())


@ultimate_bp.route("/evolution/log", methods=["GET"])
def evolution_log():
    if not evolution_loop:
        return _unavailable("evolution_loop")
    log = evolution_loop._load_log()
    n = int(request.args.get("n", 20))
    return _json_ok(entries=log[-n:][::-1])


@ultimate_bp.route("/evolution/start", methods=["POST"])
def evolution_start():
    if not evolution_loop:
        return _unavailable("evolution_loop")
    data = request.get_json(silent=True) or {}
    hours = float(data.get("interval_hours", evolution_loop.DEFAULT_INTERVAL_HOURS))
    ok = evolution_loop.start_evolution(interval_hours=hours)
    return _json_ok(started=ok, interval_hours=hours)


@ultimate_bp.route("/evolution/stop", methods=["POST"])
def evolution_stop():
    if not evolution_loop:
        return _unavailable("evolution_loop")
    return _json_ok(stopped=evolution_loop.stop_evolution())


# ============================================================================
# PROACTIVE PLANNER
# ============================================================================

@ultimate_bp.route("/proactive/status", methods=["GET"])
def proactive_status():
    if not proactive_planner:
        return _unavailable("proactive_planner")
    return jsonify(proactive_planner.get_proactive_status())


@ultimate_bp.route("/proactive/run", methods=["POST"])
def proactive_run():
    if not proactive_planner:
        return _unavailable("proactive_planner")
    return jsonify(proactive_planner.run_now())


@ultimate_bp.route("/proactive/pending", methods=["GET"])
def proactive_pending():
    if not proactive_planner:
        return _unavailable("proactive_planner")
    n = int(request.args.get("n", 10))
    return _json_ok(items=proactive_planner.get_pending_suggestions(n=n))


@ultimate_bp.route("/proactive/mark", methods=["POST"])
def proactive_mark():
    if not proactive_planner:
        return _unavailable("proactive_planner")
    data = request.get_json(silent=True) or {}
    title = data.get("title", "")
    status = data.get("status", "dismissed")
    if status not in ("accepted", "dismissed", "done"):
        return _json_err("status must be accepted/dismissed/done")
    ok = proactive_planner.mark_suggestion(title, status)
    return _json_ok(marked=ok, title=title, status=status)


@ultimate_bp.route("/proactive/start", methods=["POST"])
def proactive_start():
    if not proactive_planner:
        return _unavailable("proactive_planner")
    data = request.get_json(silent=True) or {}
    mins = float(data.get("interval_minutes", proactive_planner.DEFAULT_INTERVAL_MINUTES))
    ok = proactive_planner.start_proactive(interval_minutes=mins)
    return _json_ok(started=ok, interval_minutes=mins)


@ultimate_bp.route("/proactive/stop", methods=["POST"])
def proactive_stop():
    if not proactive_planner:
        return _unavailable("proactive_planner")
    return _json_ok(stopped=proactive_planner.stop_proactive())


# ============================================================================
# TWEAK ENGINE
# ============================================================================

@ultimate_bp.route("/tweak/list", methods=["GET"])
def tweak_list():
    if not tweak_engine:
        return _unavailable("tweak_engine")
    return jsonify(tweak_engine.list_tweakable())


@ultimate_bp.route("/tweak/apply", methods=["POST"])
def tweak_apply():
    if not tweak_engine:
        return _unavailable("tweak_engine")
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    value = data.get("value")
    if not name or value is None:
        return _json_err("name and value required")
    return jsonify(tweak_engine.tweak(name, value))


@ultimate_bp.route("/tweak/rollback", methods=["POST"])
def tweak_rollback():
    if not tweak_engine:
        return _unavailable("tweak_engine")
    return jsonify(tweak_engine.rollback())


@ultimate_bp.route("/tweak/log", methods=["GET"])
def tweak_log():
    if not tweak_engine:
        return _unavailable("tweak_engine")
    n = int(request.args.get("n", 30))
    return _json_ok(entries=tweak_engine.get_tweak_log(n=n))


@ultimate_bp.route("/tweak/backups", methods=["GET"])
def tweak_backups():
    if not tweak_engine:
        return _unavailable("tweak_engine")
    return _json_ok(backups=tweak_engine.list_backups())


# ============================================================================
# SKILL LEARNER
# ============================================================================

@ultimate_bp.route("/skills/list", methods=["GET"])
def skills_list():
    if not skill_learner:
        return _unavailable("skill_learner")
    return _json_ok(skills=skill_learner.get_skills())


@ultimate_bp.route("/skills/learn", methods=["POST"])
def skills_learn():
    if not skill_learner:
        return _unavailable("skill_learner")
    return jsonify(skill_learner.learn_from_recent())


@ultimate_bp.route("/skills/match", methods=["POST"])
def skills_match():
    if not skill_learner:
        return _unavailable("skill_learner")
    data = request.get_json(silent=True) or {}
    req = data.get("request", "")
    skill = skill_learner.find_matching_skill(req)
    return _json_ok(matched=bool(skill), skill=skill)


@ultimate_bp.route("/skills/apply", methods=["POST"])
def skills_apply():
    if not skill_learner:
        return _unavailable("skill_learner")
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    params = data.get("params", {}) or {}
    rendered = skill_learner.apply_skill(name, **params)
    if rendered is None:
        return _json_err(f"could not apply skill {name} (missing params or unknown)")
    # Optionally pass straight to orchestrator
    if data.get("execute") and brain_orchestrator and task_graph:
        try:
            graph = task_graph.graph_from_plan(f"skill:{name}", rendered)
            graph.save()
            result = brain_orchestrator.execute_graph(graph)
            return _json_ok(rendered=rendered, executed=True, result=result)
        except Exception as e:
            return _json_err(f"execution failed: {e}", 500)
    return _json_ok(rendered=rendered, executed=False)


@ultimate_bp.route("/skills/remove/<name>", methods=["POST", "DELETE"])
def skills_remove(name):
    if not skill_learner:
        return _unavailable("skill_learner")
    return _json_ok(removed=skill_learner.remove_skill(name), name=name)


@ultimate_bp.route("/skills/status", methods=["GET"])
def skills_status():
    if not skill_learner:
        return _unavailable("skill_learner")
    return jsonify(skill_learner.get_skill_status())


# ============================================================================
# PREDICTIVE MONITOR
# ============================================================================

@ultimate_bp.route("/predictive/status", methods=["GET"])
def predictive_status():
    if not predictive_monitor:
        return _unavailable("predictive_monitor")
    return jsonify(predictive_monitor.get_monitor_status())


@ultimate_bp.route("/predictive/check", methods=["POST"])
def predictive_check():
    if not predictive_monitor:
        return _unavailable("predictive_monitor")
    return jsonify(predictive_monitor.run_check())


@ultimate_bp.route("/predictive/anomalies", methods=["GET"])
def predictive_anomalies():
    if not predictive_monitor:
        return _unavailable("predictive_monitor")
    n = int(request.args.get("n", 20))
    return _json_ok(anomalies=predictive_monitor.get_anomaly_log(n=n))


@ultimate_bp.route("/predictive/start", methods=["POST"])
def predictive_start():
    if not predictive_monitor:
        return _unavailable("predictive_monitor")
    data = request.get_json(silent=True) or {}
    interval = float(data.get("interval_sec", predictive_monitor.DEFAULT_INTERVAL_SEC))
    ok = predictive_monitor.start_monitor(interval_sec=interval)
    return _json_ok(started=ok, interval_sec=interval)


@ultimate_bp.route("/predictive/stop", methods=["POST"])
def predictive_stop():
    if not predictive_monitor:
        return _unavailable("predictive_monitor")
    return _json_ok(stopped=predictive_monitor.stop_monitor())


# ============================================================================
# HUMAN-IN-THE-LOOP APPROVAL
# ============================================================================

@ultimate_bp.route("/approval/pending", methods=["GET"])
def approval_pending():
    if not human_interface:
        return _unavailable("human_interface")
    return _json_ok(pending=human_interface.list_pending())


@ultimate_bp.route("/approval/decide", methods=["POST"])
def approval_decide():
    if not human_interface:
        return _unavailable("human_interface")
    data = request.get_json(silent=True) or {}
    req_id = data.get("id", "")
    decision = data.get("decision", "")
    reason = data.get("reason", "")
    if decision not in ("approved", "denied"):
        return _json_err("decision must be 'approved' or 'denied'")
    ok = human_interface.decide(req_id, decision, reason=reason)
    return _json_ok(decided=ok, id=req_id, decision=decision)


@ultimate_bp.route("/approval/audit", methods=["GET"])
def approval_audit():
    if not human_interface:
        return _unavailable("human_interface")
    n = int(request.args.get("n", 50))
    return _json_ok(audit=human_interface.get_audit_log(n=n))


@ultimate_bp.route("/approval/status", methods=["GET"])
def approval_status():
    if not human_interface:
        return _unavailable("human_interface")
    return jsonify(human_interface.get_status())


@ultimate_bp.route("/approval/auto/<kind>", methods=["POST"])
def approval_auto(kind):
    if not human_interface:
        return _unavailable("human_interface")
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))
    human_interface.auto_approve_kind(kind, enabled)
    return _json_ok(kind=kind, enabled=enabled, settings=human_interface.get_settings())


# ============================================================================
# MASTER STATUS
# ============================================================================

@ultimate_bp.route("/status", methods=["GET"])
def master_status():
    s: Dict = {}
    if vector_store:
        try: s["vector_store"] = vector_store.stats()
        except Exception as e: s["vector_store"] = {"error": str(e)}
    if model_selector:
        try: s["model_selector"] = model_selector.status()
        except Exception as e: s["model_selector"] = {"error": str(e)}
    if memory_distiller:
        try: s["distiller"] = memory_distiller.get_distiller_status()
        except Exception as e: s["distiller"] = {"error": str(e)}
    if evolution_loop:
        try: s["evolution"] = evolution_loop.get_evolution_status()
        except Exception as e: s["evolution"] = {"error": str(e)}
    if proactive_planner:
        try: s["proactive"] = proactive_planner.get_proactive_status()
        except Exception as e: s["proactive"] = {"error": str(e)}
    if skill_learner:
        try: s["skills"] = skill_learner.get_skill_status()
        except Exception as e: s["skills"] = {"error": str(e)}
    if predictive_monitor:
        try: s["predictive"] = predictive_monitor.get_monitor_status()
        except Exception as e: s["predictive"] = {"error": str(e)}
    if human_interface:
        try: s["approval"] = human_interface.get_status()
        except Exception as e: s["approval"] = {"error": str(e)}
    s["modules_loaded"] = {
        "vector_store":       vector_store is not None,
        "research_engine":    research_engine is not None,
        "brain_orchestrator": brain_orchestrator is not None,
        "task_graph":         task_graph is not None,
        "model_selector":     model_selector is not None,
        "memory_distiller":   memory_distiller is not None,
        "evolution_loop":     evolution_loop is not None,
        "proactive_planner":  proactive_planner is not None,
        "tweak_engine":       tweak_engine is not None,
        "skill_learner":      skill_learner is not None,
        "predictive_monitor": predictive_monitor is not None,
        "human_interface":    human_interface is not None,
    }
    return jsonify(s)


# ============================================================================
# BACKGROUND LOOP STARTUP
# ============================================================================

def start_ultimate_loops(
    distiller_hours: float = 6,
    evolution_hours: float = 12,
    proactive_minutes: float = 30,
    predictive_seconds: float = 60,
    skill_hours: float = 6,
    enable: bool = True,
) -> Dict:
    """Called from app.py after app initialises. Starts background loops."""
    started = {}
    if not enable:
        return {"enabled": False}
    if memory_distiller:
        try:
            started["distiller"] = memory_distiller.start_distiller(interval_hours=distiller_hours)
        except Exception as e:
            started["distiller"] = f"error: {e}"
    if evolution_loop:
        try:
            started["evolution"] = evolution_loop.start_evolution(interval_hours=evolution_hours)
        except Exception as e:
            started["evolution"] = f"error: {e}"
    if proactive_planner:
        try:
            started["proactive"] = proactive_planner.start_proactive(interval_minutes=proactive_minutes)
        except Exception as e:
            started["proactive"] = f"error: {e}"
    if predictive_monitor:
        try:
            started["predictive"] = predictive_monitor.start_monitor(interval_sec=predictive_seconds)
        except Exception as e:
            started["predictive"] = f"error: {e}"
    # skill_learner — previously dormant. Auto-learn every 6h like distiller.
    if skill_learner and hasattr(skill_learner, "start_skill_learner"):
        try:
            started["skill_learner"] = skill_learner.start_skill_learner(interval_hours=skill_hours)
        except Exception as e:
            started["skill_learner"] = f"error: {e}"
    return started
