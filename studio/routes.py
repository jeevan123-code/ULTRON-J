"""
studio/routes.py — Flask blueprint for LEBENX STUDIO.

Every route resolves its project through `db.assert_project(project_id,
workspace)` before touching any child row, so ownership is enforced in one
place rather than re-derived per handler.

Nothing here does expensive work inline. Generation, rendering, and missions
all enqueue and return immediately; the client polls the status endpoints.
The one deliberate exception is the synchronous script/research helpers,
which the wizard needs interactively and which are LLM calls of a few
seconds, not provider jobs of several minutes.

API keys never cross the wire back to the client: `registry.describe_all()`
redacts them, and the settings route accepts a key but never returns one.
"""

from __future__ import annotations

import os
from flask import Blueprint, Response, jsonify, render_template, request, send_file

from . import (agents, captions, cost, db, handlers, jobs, pipeline, prompts,
               quality, render, timeline as tl)
from .providers import registry
from .storage import get_storage

studio_bp = Blueprint("studio", __name__, url_prefix="/studio")


# =============================================================================
# HELPERS
# =============================================================================

def _workspace() -> str:
    """Resolve the calling workspace.

    Ultron-J is single-tenant today, so this defaults to 'default'. The
    header hook is what lets the same code serve multiple workspaces later
    without every query changing.
    """
    return (request.headers.get("X-Studio-Workspace")
            or request.args.get("workspace")
            or "default").strip()[:64] or "default"


def _owner() -> str:
    return (request.headers.get("X-Studio-User") or "").strip()[:120]


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _project_or_404(project_id: str) -> dict:
    return db.assert_project(project_id, _workspace())


def _err(message: str, code: int = 400, **extra):
    return jsonify({"error": message, **extra}), code


@studio_bp.errorhandler(db.NotFound)
def _handle_not_found(exc):
    return jsonify({"error": str(exc)}), 404


@studio_bp.errorhandler(registry.NoProviderAvailable)
def _handle_no_provider(exc):
    """Refusals carry the reason and the fix, never a silent degradation."""
    return jsonify({
        "error": exc.message,
        "kind": exc.kind,
        "providers": exc.candidates,
        "remedy": "Connect a provider in Studio Settings, then retry.",
    }), 409


# =============================================================================
# UI
# =============================================================================

@studio_bp.route("/")
def studio_home():
    return render_template("studio.html")


# =============================================================================
# PROJECTS
# =============================================================================

VIDEO_TYPES = ["youtube_video", "youtube_short", "documentary", "explainer",
               "news_video", "cinematic_story", "podcast_clip", "custom"]
DURATION_PRESETS = [15, 30, 60, 180, 300, 600]


@studio_bp.route("/api/config")
def api_config():
    """Everything the UI needs to render its option lists honestly."""
    workspace = _workspace()
    return jsonify({
        "video_types": VIDEO_TYPES,
        "duration_presets": DURATION_PRESETS,
        "styles": prompts.list_styles(),
        "caption_styles": captions.list_styles(),
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "asset_types": ["ai_image", "ai_video", "stock", "user_upload",
                        "text_animation", "screen_recording"],
        "transitions": ["cut", "fade", "dissolve", "slide"],
        "approval_levels": list(pipeline.APPROVAL_LEVELS),
        "modes": ["full_auto", "assisted", "manual"],
        "stages": [{"id": s, "label": pipeline.STAGE_LABELS[s]}
                   for s in pipeline.STAGES],
        "providers": registry.describe_all(workspace),
        "render": render.export_settings(),
        "budget": cost.get_budget(workspace),
        "workers": jobs.worker_status(),
    })


@studio_bp.route("/api/projects", methods=["GET"])
def list_projects():
    projects = db.fetch_all(
        "SELECT * FROM studio_project WHERE workspace=? AND archived=0 "
        "ORDER BY updated_at DESC LIMIT 100", (_workspace(),))
    for project in projects:
        counts = db.fetch_one(
            """SELECT (SELECT COUNT(*) FROM scene s JOIN storyboard b
                        ON b.id=s.storyboard_id
                        WHERE s.project_id=? AND b.is_current=1) AS scenes,
                      (SELECT COUNT(*) FROM media_asset WHERE project_id=?) AS assets""",
            (project["id"], project["id"]))
        project.update(counts or {})
    return jsonify({"projects": projects})


@studio_bp.route("/api/projects", methods=["POST"])
def create_project():
    """Create a project from an idea, with an inferred brief the user can edit."""
    body = _body()
    idea = (body.get("idea") or "").strip()
    if not idea:
        return _err("an idea is required")

    workspace = _workspace()
    project_id = db.new_id("proj")
    now = db.now()

    video_type = body.get("video_type") or "youtube_video"
    duration = int(body.get("duration_s") or 300)
    aspect = body.get("aspect_ratio") or ("9:16" if video_type == "youtube_short"
                                          else "16:9")
    if video_type == "youtube_short":
        duration = min(duration, 60)

    db.insert("studio_project", {
        "id": project_id, "workspace": workspace, "owner": _owner(),
        "title": (body.get("title") or idea)[:200], "idea": idea,
        "video_type": video_type,
        "mode": body.get("mode") or "assisted",
        "approval_level": body.get("approval_level") or "expensive",
        "status": "draft", "stage": "brief",
        "created_at": now, "updated_at": now,
    })

    db.insert("video_brief", {
        "id": db.new_id("brf"), "project_id": project_id,
        "topic": (body.get("topic") or idea)[:500],
        "audience": body.get("audience") or "",
        "platform": body.get("platform") or "youtube",
        "duration_s": duration,
        "tone": body.get("tone") or "",
        "visual_style": body.get("visual_style") or "cinematic",
        "language": body.get("language") or "en",
        "aspect_ratio": aspect,
        "notes": "", "approved": 0,
        "created_at": now, "updated_at": now,
    })

    tl.get_or_create(project_id, aspect_ratio=aspect)
    return jsonify(_project_payload(project_id)), 201


@studio_bp.route("/api/projects/<project_id>")
def get_project(project_id: str):
    _project_or_404(project_id)
    return jsonify(_project_payload(project_id))


def _project_payload(project_id: str) -> dict:
    project = db.fetch_one("SELECT * FROM studio_project WHERE id=?", (project_id,))
    return {
        "project": project,
        "brief": db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                              (project_id,)),
        "research": agents.get_research(project_id),
        "script": agents.get_script(project_id),
        "storyboard": agents.get_storyboard(project_id),
        "mission": pipeline.status(project_id).get("mission"),
        "quality": quality.latest(project_id),
    }


@studio_bp.route("/api/projects/<project_id>", methods=["PATCH"])
def update_project(project_id: str):
    _project_or_404(project_id)
    body = _body()
    allowed = {"title", "mode", "approval_level", "status", "stage", "video_type"}
    patch = {k: v for k, v in body.items() if k in allowed}
    if not patch:
        return _err("no updatable fields supplied")
    db.update("studio_project", project_id, patch)
    return jsonify(_project_payload(project_id))


@studio_bp.route("/api/projects/<project_id>", methods=["DELETE"])
def archive_project(project_id: str):
    _project_or_404(project_id)
    db.update("studio_project", project_id, {"archived": 1})
    return jsonify({"ok": True, "archived": True,
                    "note": "Project archived. Its media is retained in the "
                            "asset library."})


# =============================================================================
# BRIEF
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/brief", methods=["PATCH"])
def update_brief(project_id: str):
    _project_or_404(project_id)
    brief = db.fetch_one("SELECT id FROM video_brief WHERE project_id=?",
                         (project_id,))
    if not brief:
        return _err("this project has no brief", 404)

    body = _body()
    allowed = {"topic", "audience", "platform", "duration_s", "tone",
               "visual_style", "language", "aspect_ratio", "notes", "approved"}
    patch = {k: v for k, v in body.items() if k in allowed}
    if "approved" in patch:
        patch["approved"] = 1 if patch["approved"] else 0
    if not patch:
        return _err("no updatable fields supplied")

    db.update("video_brief", brief["id"], patch)

    if "aspect_ratio" in patch:
        # Aspect ratio drives the render canvas, so the timeline must follow.
        timeline = db.fetch_one("SELECT id FROM timeline WHERE project_id=?",
                                (project_id,))
        if timeline:
            width, height = tl._dimensions(patch["aspect_ratio"])
            db.update("timeline", timeline["id"],
                      {"aspect_ratio": patch["aspect_ratio"],
                       "width": width, "height": height})

    return jsonify({"brief": db.fetch_one(
        "SELECT * FROM video_brief WHERE project_id=?", (project_id,))})


# =============================================================================
# RESEARCH / SCRIPT / STORYBOARD
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/research", methods=["POST"])
def run_research(project_id: str):
    _project_or_404(project_id)
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    body = _body()
    try:
        report = agents.research(
            project_id, body.get("topic") or brief.get("topic", ""),
            audience=brief.get("audience", ""),
            use_search=body.get("use_search", True))
    except agents.AgentError as exc:
        return _err(str(exc), 502)
    return jsonify({"research": report})


@studio_bp.route("/api/projects/<project_id>/research", methods=["PATCH"])
def edit_research(project_id: str):
    _project_or_404(project_id)
    report = db.fetch_one("SELECT id FROM research_report WHERE project_id=?",
                          (project_id,))
    if not report:
        return _err("no research report to edit", 404)

    body = _body()
    patch = {}
    for field in ("key_points", "facts", "statistics", "misconceptions",
                  "sources", "uncertainties"):
        if field in body:
            patch[field] = db._dumps(body[field])
    if "hook" in body:
        patch["hook"] = str(body["hook"])
    if "status" in body:
        patch["status"] = str(body["status"])
    if not patch:
        return _err("no updatable fields supplied")

    db.update("research_report", report["id"], patch)
    return jsonify({"research": agents.get_research(project_id)})


@studio_bp.route("/api/projects/<project_id>/script", methods=["POST"])
def generate_script(project_id: str):
    _project_or_404(project_id)
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    body = _body()
    try:
        if body.get("mode") or body.get("section"):
            current = agents.get_script(project_id)
            if not current:
                return _err("no script to rewrite", 404)
            script = agents.rewrite_script(
                project_id, brief=brief, script=current,
                mode=body.get("mode", ""), instruction=body.get("instruction", ""),
                section=body.get("section", ""))
        else:
            script = agents.write_script(
                project_id, brief=brief,
                research_report=agents.get_research(project_id),
                instruction=body.get("instruction", ""))
    except agents.AgentError as exc:
        return _err(str(exc), 502)

    agents.save_script(project_id, script)
    return jsonify({"script": agents.get_script(project_id)})


@studio_bp.route("/api/projects/<project_id>/script", methods=["PATCH"])
def edit_script(project_id: str):
    """Direct manual editing — always available, per the spec."""
    _project_or_404(project_id)
    body = _body()

    segments = body.get("segments")
    if isinstance(segments, list):
        script = {
            "title": body.get("title", ""),
            "hook": body.get("hook", ""),
            "call_to_action": body.get("call_to_action", ""),
            "segments": [
                {"idx": i,
                 "start_s": float(s.get("start_s", 0)),
                 "end_s": float(s.get("end_s", 0)),
                 "text": str(s.get("text", ""))}
                for i, s in enumerate(segments) if isinstance(s, dict)
            ],
        }
        script["body"] = "\n\n".join(s["text"] for s in script["segments"])
        script["word_count"] = sum(len(s["text"].split()) for s in script["segments"])
        agents.save_script(project_id, script, source="user")
        return jsonify({"script": agents.get_script(project_id)})

    current = agents.get_script(project_id)
    if not current:
        return _err("no script to edit", 404)
    patch = {k: v for k, v in body.items()
             if k in ("title", "hook", "body", "call_to_action")}
    if not patch:
        return _err("no updatable fields supplied")
    patch["source"] = "user"
    db.update("video_script", current["id"], patch)
    return jsonify({"script": agents.get_script(project_id)})


@studio_bp.route("/api/projects/<project_id>/storyboard", methods=["POST"])
def generate_storyboard(project_id: str):
    _project_or_404(project_id)
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    script = agents.get_script(project_id)
    if not script:
        return _err("write a script before creating a storyboard")
    try:
        board = agents.direct(project_id, brief=brief, script=script)
    except agents.AgentError as exc:
        return _err(str(exc), 502)
    agents.save_storyboard(project_id, board, brief=brief, workspace=_workspace())
    return jsonify({"storyboard": agents.get_storyboard(project_id)})


@studio_bp.route("/api/projects/<project_id>/storyboard")
def get_storyboard(project_id: str):
    _project_or_404(project_id)
    return jsonify({"storyboard": agents.get_storyboard(project_id)})


# =============================================================================
# SCENES
# =============================================================================

@studio_bp.route("/api/scenes/<scene_id>", methods=["PATCH"])
def update_scene(scene_id: str):
    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (scene_id,))
    if not scene:
        return _err("scene not found", 404)
    _project_or_404(scene["project_id"])

    body = _body()
    allowed = {"narration", "visual_description", "camera", "transition",
               "transition_duration", "asset_type", "generation_prompt",
               "negative_prompt", "duration_s", "selected_asset_id", "status"}
    patch = {k: v for k, v in body.items() if k in allowed}
    if not patch:
        return _err("no updatable fields supplied")

    db.update("scene", scene_id, patch)
    if "duration_s" in patch:
        tl._reflow_scenes(scene["project_id"])
    return jsonify({"scene": db.fetch_one("SELECT * FROM scene WHERE id=?",
                                          (scene_id,),
                                          json_fields=("character_refs",))})


@studio_bp.route("/api/scenes/<scene_id>/prompt", methods=["POST"])
def regenerate_scene_prompt(scene_id: str):
    """Re-run the visual prompt engine for one scene."""
    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (scene_id,),
                         json_fields=("character_refs",))
    if not scene:
        return _err("scene not found", 404)
    _project_or_404(scene["project_id"])

    body = _body()
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (scene["project_id"],)) or {}
    kind = "video" if scene["asset_type"] == "ai_video" else "image"

    try:
        provider = registry.resolve(kind, _workspace(),
                                    preferred=body.get("provider", ""))
        provider_name, warning = provider.name, prompts.consistency_warning(
            provider.name, provider)
    except registry.NoProviderAvailable:
        provider_name, warning = "", None

    built = prompts.build_prompt(
        description=body.get("description") or scene["visual_description"],
        style=body.get("style") or brief.get("visual_style", "cinematic"),
        camera=scene["camera"], provider=provider_name, kind=kind,
        project_id=scene["project_id"],
        character_refs=scene.get("character_refs") or [],
        aspect_ratio=brief.get("aspect_ratio", "16:9"))

    db.update("scene", scene_id, {"generation_prompt": built["prompt"],
                                  "negative_prompt": built["negative_prompt"]})
    return jsonify({"prompt": built, "consistency_warning": warning})


@studio_bp.route("/api/scenes/<scene_id>", methods=["DELETE"])
def delete_scene(scene_id: str):
    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (scene_id,))
    if not scene:
        return _err("scene not found", 404)
    _project_or_404(scene["project_id"])
    db.execute("DELETE FROM scene WHERE id=?", (scene_id,))
    _renumber_scenes(scene["storyboard_id"])
    tl._reflow_scenes(scene["project_id"])
    return jsonify({"ok": True})


@studio_bp.route("/api/scenes/<scene_id>/duplicate", methods=["POST"])
def duplicate_scene(scene_id: str):
    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (scene_id,))
    if not scene:
        return _err("scene not found", 404)
    _project_or_404(scene["project_id"])

    clone = dict(scene)
    clone.update({
        "id": db.new_id("scn"), "idx": scene["idx"] + 1,
        # A duplicate has no asset of its own — copying the reference would
        # imply it had been generated when it has not.
        "selected_asset_id": None, "status": "pending", "error": "",
        "created_at": db.now(), "updated_at": db.now(),
    })
    db.execute("UPDATE scene SET idx = idx + 1 WHERE storyboard_id=? AND idx > ?",
               (scene["storyboard_id"], scene["idx"]))
    db.insert("scene", clone)
    tl._reflow_scenes(scene["project_id"])
    return jsonify({"scene": clone}), 201


@studio_bp.route("/api/scenes/<scene_id>/split", methods=["POST"])
def split_scene(scene_id: str):
    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (scene_id,))
    if not scene:
        return _err("scene not found", 404)
    _project_or_404(scene["project_id"])

    at = float(_body().get("at_s") or scene["duration_s"] / 2)
    if at <= 0.3 or at >= scene["duration_s"] - 0.3:
        return _err("split point is too close to a scene boundary")

    db.update("scene", scene_id, {"duration_s": round(at, 2)})
    db.execute("UPDATE scene SET idx = idx + 1 WHERE storyboard_id=? AND idx > ?",
               (scene["storyboard_id"], scene["idx"]))

    second = dict(scene)
    second.update({
        "id": db.new_id("scn"), "idx": scene["idx"] + 1,
        "duration_s": round(scene["duration_s"] - at, 2),
        "start_s": round(scene["start_s"] + at, 2),
        "selected_asset_id": None, "status": "pending", "error": "",
        "created_at": db.now(), "updated_at": db.now(),
    })
    db.insert("scene", second)
    tl._reflow_scenes(scene["project_id"])
    return jsonify({"scenes": [db.fetch_one("SELECT * FROM scene WHERE id=?",
                                            (scene_id,)), second]}), 201


@studio_bp.route("/api/scenes/<scene_id>/merge", methods=["POST"])
def merge_scene(scene_id: str):
    """Merge this scene with the next one."""
    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (scene_id,))
    if not scene:
        return _err("scene not found", 404)
    _project_or_404(scene["project_id"])

    nxt = db.fetch_one("SELECT * FROM scene WHERE storyboard_id=? AND idx=?",
                       (scene["storyboard_id"], scene["idx"] + 1))
    if not nxt:
        return _err("there is no following scene to merge with")

    db.update("scene", scene_id, {
        "duration_s": round(scene["duration_s"] + nxt["duration_s"], 2),
        "narration": f"{scene['narration']} {nxt['narration']}".strip(),
        "transition": nxt["transition"],
    })
    db.execute("DELETE FROM scene WHERE id=?", (nxt["id"],))
    _renumber_scenes(scene["storyboard_id"])
    tl._reflow_scenes(scene["project_id"])
    return jsonify({"ok": True, "scene": db.fetch_one(
        "SELECT * FROM scene WHERE id=?", (scene_id,))})


@studio_bp.route("/api/projects/<project_id>/scenes/reorder", methods=["POST"])
def reorder_scenes(project_id: str):
    _project_or_404(project_id)
    order = _body().get("scene_ids")
    if not isinstance(order, list) or not order:
        return _err("scene_ids must be a non-empty list")

    owned = {s["id"] for s in db.fetch_all(
        "SELECT id FROM scene WHERE project_id=?", (project_id,))}
    if not set(order).issubset(owned):
        return _err("one or more scenes do not belong to this project", 403)

    for idx, sid in enumerate(order):
        db.update("scene", sid, {"idx": idx})
    tl._reflow_scenes(project_id)
    return jsonify({"ok": True, "storyboard": agents.get_storyboard(project_id)})


def _renumber_scenes(storyboard_id: str) -> None:
    scenes = db.fetch_all("SELECT id FROM scene WHERE storyboard_id=? ORDER BY idx",
                          (storyboard_id,))
    for idx, scene in enumerate(scenes):
        db.update("scene", scene["id"], {"idx": idx})


# =============================================================================
# GENERATION
# =============================================================================

@studio_bp.route("/api/scenes/<scene_id>/generate", methods=["POST"])
def generate_scene(scene_id: str):
    """Queue generation for one scene, after a budget check."""
    scene = db.fetch_one("SELECT * FROM scene WHERE id=?", (scene_id,))
    if not scene:
        return _err("scene not found", 404)
    project = _project_or_404(scene["project_id"])

    body = _body()
    workspace = _workspace()
    kind = body.get("kind") or ("video" if scene["asset_type"] == "ai_video"
                                else "image")
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (scene["project_id"],)) or {}

    require = "image_to_video" if (kind == "video" and body.get("image_url")) else ""
    provider = registry.resolve(kind, workspace,
                                preferred=body.get("provider", ""), require=require)

    from .providers.base import GenerationRequest
    req = GenerationRequest(
        prompt=body.get("prompt") or scene["generation_prompt"],
        negative_prompt=scene["negative_prompt"],
        model=body.get("model") or "",
        aspect_ratio=brief.get("aspect_ratio", "16:9"),
        resolution=body.get("resolution", ""),
        duration_s=scene["duration_s"] if kind == "video" else 0,
        variations=int(body.get("variations") or 1),
        image_url=body.get("image_url", ""),
    )
    estimate = cost.estimate(kind, provider, req, quantity=req.variations)
    decision = cost.check_budget(workspace, estimate.amount)

    if not decision["allowed"] and not body.get("confirm_over_budget"):
        return jsonify({
            "error": "blocked by budget", "reason": decision["reason"],
            "estimate": estimate.to_dict(), "budget": decision["budget"],
            "hint": "Raise the monthly budget, or resend with "
                    "confirm_over_budget=true to proceed anyway.",
        }), 402

    # Confirm-before-spend, when the project asks for it.
    if (project["approval_level"] != "full_auto"
            and estimate.amount is not None
            and not body.get("confirm")):
        return jsonify({
            "requires_confirmation": True,
            "estimate": estimate.to_dict(),
            "budget": decision["budget"],
            "provider": provider.name,
            "note": "This is an estimate, not a guaranteed price. Resend with "
                    "confirm=true to generate.",
        }), 202

    job = jobs.enqueue(
        project_id=scene["project_id"], workspace=workspace, job_type=kind,
        scene_id=scene_id, prompt=req.prompt, provider=provider.name,
        model=req.model, owner=_owner(), cost_estimate=estimate.amount,
        settings={"aspect_ratio": req.aspect_ratio, "resolution": req.resolution,
                  "negative_prompt": req.negative_prompt,
                  "duration_s": req.duration_s, "variations": req.variations,
                  "image_url": req.image_url},
    )
    db.update("scene", scene_id, {"status": "queued", "error": ""})
    return jsonify({"job": job, "estimate": estimate.to_dict()}), 202


@studio_bp.route("/api/projects/<project_id>/generate-all", methods=["POST"])
def generate_all_scenes(project_id: str):
    """Queue every ungenerated scene. Blocked scenes are reported, not hidden."""
    _project_or_404(project_id)
    workspace = _workspace()
    body = _body()

    board = agents.get_storyboard(project_id)
    if not board:
        return _err("no storyboard to generate from", 404)

    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    estimate = cost.estimate_project(project_id, workspace)
    decision = cost.check_budget(workspace, estimate["known_total"])

    if not decision["allowed"] and not body.get("confirm_over_budget"):
        return jsonify({"error": "blocked by budget", "reason": decision["reason"],
                        "estimate": estimate, "budget": decision["budget"]}), 402

    if not body.get("confirm"):
        return jsonify({"requires_confirmation": True, "estimate": estimate,
                        "budget": decision["budget"],
                        "note": "Estimates are not guaranteed prices."}), 202

    queued, blocked = [], []
    for scene in board["scenes"]:
        if scene["selected_asset_id"] or scene["asset_type"] not in ("ai_image", "ai_video"):
            continue
        kind = "video" if scene["asset_type"] == "ai_video" else "image"
        try:
            registry.resolve(kind, workspace)
        except registry.NoProviderAvailable as exc:
            blocked.append({"scene": scene["idx"], "reason": exc.message})
            db.update("scene", scene["id"],
                      {"status": "blocked", "error": exc.message[:500]})
            continue

        job = jobs.enqueue(
            project_id=project_id, workspace=workspace, job_type=kind,
            scene_id=scene["id"], prompt=scene["generation_prompt"],
            owner=_owner(),
            settings={"aspect_ratio": brief.get("aspect_ratio", "16:9"),
                      "negative_prompt": scene["negative_prompt"],
                      "duration_s": scene["duration_s"]},
            idempotency_key=f"{project_id}:{scene['id']}:{kind}:v{board['version']}",
        )
        queued.append(job["id"])
        db.update("scene", scene["id"], {"status": "queued", "error": ""})

    return jsonify({"queued": len(queued), "job_ids": queued,
                    "blocked": blocked, "estimate": estimate}), 202


@studio_bp.route("/api/jobs/<job_id>")
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        return _err("job not found", 404)
    _project_or_404(job["project_id"])
    job["logs"] = db.job_logs(job_id, limit=100)
    return jsonify({"job": job})


@studio_bp.route("/api/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        return _err("job not found", 404)
    _project_or_404(job["project_id"])
    return jsonify(jobs.cancel_job(job_id))


@studio_bp.route("/api/jobs/<job_id>/retry", methods=["POST"])
def retry_job(job_id: str):
    """Retry a failed scene — optionally on a different provider or prompt.

    This is the failure-recovery path: one scene failing never fails the
    project, and the user can retry, switch provider, edit the prompt, or
    skip.
    """
    job = jobs.get_job(job_id)
    if not job:
        return _err("job not found", 404)
    _project_or_404(job["project_id"])

    body = _body()
    settings = dict(job["settings"] or {})
    prompt = body.get("prompt") or job["prompt"]
    provider_name = body.get("provider") or job["provider"]

    # Reformat the prompt when moving to a different provider.
    if body.get("provider") and body["provider"] != job["provider"] and not body.get("prompt"):
        prompt = prompts.rewrite_for_provider(
            prompt, from_provider=job["provider"], to_provider=body["provider"],
            kind=job["job_type"])

    new_job = jobs.enqueue(
        project_id=job["project_id"], workspace=job["workspace"],
        job_type=job["job_type"], scene_id=job["scene_id"] or "",
        prompt=prompt, provider=provider_name, model=body.get("model") or job["model"],
        settings=settings, owner=_owner(),
    )
    if job["scene_id"]:
        db.update("scene", job["scene_id"],
                  {"status": "queued", "error": "", "generation_prompt": prompt})
    return jsonify({"job": new_job}), 202


@studio_bp.route("/api/projects/<project_id>/jobs")
def project_jobs(project_id: str):
    _project_or_404(project_id)
    return jsonify({"jobs": jobs.list_jobs(project_id),
                    "workers": jobs.worker_status()})


# =============================================================================
# VOICE
# =============================================================================

@studio_bp.route("/api/voices")
def list_voices():
    workspace = _workspace()
    language = request.args.get("language", "")
    out = []
    for provider in registry.dispatchable("voice", workspace):
        for voice in provider.list_voices(language):
            out.append({"id": voice.id, "name": voice.name,
                        "language": voice.language, "gender": voice.gender,
                        "preview_url": voice.preview_url,
                        "provider": provider.name})
    return jsonify({"voices": out, "count": len(out)})


@studio_bp.route("/api/projects/<project_id>/voice", methods=["POST"])
def generate_voice(project_id: str):
    """Queue narration for every scene, or one named scene."""
    _project_or_404(project_id)
    workspace = _workspace()
    body = _body()

    registry.resolve("voice", workspace, preferred=body.get("provider", ""))

    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    board = agents.get_storyboard(project_id)
    if not board:
        return _err("no storyboard to narrate", 404)

    scene_id = body.get("scene_id")
    scenes = ([s for s in board["scenes"] if s["id"] == scene_id] if scene_id
              else board["scenes"])
    if not scenes:
        return _err("scene not found", 404)

    queued = []
    for scene in scenes:
        if not scene["narration"].strip():
            continue
        queued.append(jobs.enqueue(
            project_id=project_id, workspace=workspace, job_type="voice",
            scene_id=scene["id"], prompt=scene["narration"],
            provider=body.get("provider", ""), owner=_owner(),
            settings={"language": body.get("language") or brief.get("language", "en"),
                      "voice_id": body.get("voice_id", ""),
                      "voice_name": body.get("voice_name", ""),
                      "speed": float(body.get("speed") or 1.0)},
        )["id"])

    return jsonify({"queued": len(queued), "job_ids": queued}), 202


@studio_bp.route("/api/projects/<project_id>/timing")
def timing_analysis(project_id: str):
    _project_or_404(project_id)
    return jsonify(tl.analyse_timing(project_id))


@studio_bp.route("/api/projects/<project_id>/timing/resolve", methods=["POST"])
def resolve_timing(project_id: str):
    _project_or_404(project_id)
    body = _body()
    scene_id = body.get("scene_id")
    action = body.get("action")
    if not scene_id or not action:
        return _err("scene_id and action are required")
    result = tl.apply_timing_resolution(project_id, scene_id, action,
                                        value=body.get("value"))
    return jsonify(result), (200 if result.get("ok") else 400)


# =============================================================================
# MUSIC
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/music", methods=["GET"])
def list_music(project_id: str):
    _project_or_404(project_id)
    return jsonify({"tracks": db.fetch_all(
        "SELECT * FROM music_track WHERE project_id=? ORDER BY created_at",
        (project_id,))})


@studio_bp.route("/api/projects/<project_id>/music", methods=["POST"])
def add_music(project_id: str):
    """Attach an uploaded audio asset as a music track.

    `rights_attested` is required for anything the user uploads: we do not
    assume a licence exists, and the QC agent flags tracks that lack one.
    """
    _project_or_404(project_id)
    body = _body()
    asset_id = body.get("asset_id")
    if not asset_id:
        return _err("asset_id is required — upload the audio first")

    asset = db.fetch_one("SELECT * FROM media_asset WHERE id=? AND project_id=?",
                         (asset_id, project_id))
    if not asset:
        return _err("audio asset not found in this project", 404)

    attested = bool(body.get("rights_attested"))
    track_id = db.new_id("mus")
    db.insert("music_track", {
        "id": track_id, "project_id": project_id, "asset_id": asset_id,
        "title": body.get("title") or asset["filename"],
        "source": body.get("source") or "upload",
        "rights_status": "user_attested" if attested else "unverified",
        "rights_note": body.get("rights_note", ""),
        "start_s": float(body.get("start_s") or 0),
        "duration_s": asset["duration_s"],
        "volume": float(body.get("volume") or 0.25),
        "fade_in_s": float(body.get("fade_in_s") or 1.5),
        "fade_out_s": float(body.get("fade_out_s") or 2.0),
        "ducking": 1 if body.get("ducking", True) else 0,
        "duck_to": float(body.get("duck_to") or 0.08),
        "scene_id": body.get("scene_id"),
        "created_at": db.now(), "updated_at": db.now(),
    })
    return jsonify({
        "track_id": track_id,
        "rights_status": "user_attested" if attested else "unverified",
        "warning": None if attested else
        "You have not confirmed you hold the rights to this music. Confirm "
        "before publishing — rendering it does not grant you a licence.",
    }), 201


@studio_bp.route("/api/music/<track_id>", methods=["PATCH"])
def update_music(track_id: str):
    track = db.fetch_one("SELECT * FROM music_track WHERE id=?", (track_id,))
    if not track:
        return _err("music track not found", 404)
    _project_or_404(track["project_id"])

    body = _body()
    allowed = {"title", "start_s", "duration_s", "volume", "fade_in_s",
               "fade_out_s", "duck_to", "rights_note"}
    patch = {k: float(v) if k not in ("title", "rights_note") else v
             for k, v in body.items() if k in allowed}
    if "ducking" in body:
        patch["ducking"] = 1 if body["ducking"] else 0
    if body.get("rights_attested"):
        patch["rights_status"] = "user_attested"
    if not patch:
        return _err("no updatable fields supplied")
    db.update("music_track", track_id, patch)
    return jsonify({"track": db.fetch_one("SELECT * FROM music_track WHERE id=?",
                                          (track_id,))})


@studio_bp.route("/api/music/<track_id>", methods=["DELETE"])
def delete_music(track_id: str):
    track = db.fetch_one("SELECT project_id FROM music_track WHERE id=?", (track_id,))
    if not track:
        return _err("music track not found", 404)
    _project_or_404(track["project_id"])
    db.execute("DELETE FROM music_track WHERE id=?", (track_id,))
    return jsonify({"ok": True})


# =============================================================================
# CAPTIONS
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/captions", methods=["GET"])
def get_captions(project_id: str):
    _project_or_404(project_id)
    track = captions.get_track(project_id, request.args.get("language", "en"))
    return jsonify({"track": track, "styles": captions.list_styles()})


@studio_bp.route("/api/projects/<project_id>/captions", methods=["POST"])
def build_captions(project_id: str):
    _project_or_404(project_id)
    body = _body()
    built = captions.build_cues(project_id)
    track_id = captions.save_track(
        project_id, style=body.get("style", "minimal"),
        language=body.get("language", "en"),
        cues=built["cues"], timing_source=built["timing_source"])
    return jsonify({"track_id": track_id, "cue_count": len(built["cues"]),
                    "timing_source": built["timing_source"],
                    "note": built["note"]}), 201


@studio_bp.route("/api/projects/<project_id>/captions", methods=["PATCH"])
def edit_captions(project_id: str):
    _project_or_404(project_id)
    body = _body()
    language = body.get("language", "en")
    track = captions.get_track(project_id, language)
    if not track:
        return _err("no caption track to edit", 404)

    patch = {}
    if isinstance(body.get("cues"), list):
        patch["cues"] = db._dumps(body["cues"])
        # Hand-edited cues are authoritative, so record that provenance.
        patch["timing_source"] = "manual"
    if body.get("style"):
        patch["style"] = body["style"]
        patch["style_config"] = db._dumps(
            body.get("style_config") or captions.CAPTION_STYLES.get(body["style"], {}))
    if "burned_in" in body:
        patch["burned_in"] = 1 if body["burned_in"] else 0
    if not patch:
        return _err("no updatable fields supplied")

    db.update("caption_track", track["id"], patch)
    return jsonify({"track": captions.get_track(project_id, language)})


@studio_bp.route("/api/projects/<project_id>/captions/export")
def export_captions(project_id: str):
    _project_or_404(project_id)
    fmt = (request.args.get("format") or "srt").lower()
    track = captions.get_track(project_id, request.args.get("language", "en"))
    if not track or not track.get("cues"):
        return _err("no captions to export", 404)

    if fmt == "vtt":
        body, mime, ext = captions.to_vtt(track["cues"]), "text/vtt", "vtt"
    elif fmt == "srt":
        body, mime, ext = captions.to_srt(track["cues"]), "application/x-subrip", "srt"
    else:
        return _err(f"unsupported caption format '{fmt}' (use srt or vtt)")

    return Response(body, mimetype=mime, headers={
        "Content-Disposition": f'attachment; filename="captions.{ext}"'})


# =============================================================================
# TIMELINE
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/timeline")
def get_timeline(project_id: str):
    _project_or_404(project_id)
    return jsonify({"timeline": tl.load(project_id)})


@studio_bp.route("/api/projects/<project_id>/timeline/assemble", methods=["POST"])
def assemble_timeline(project_id: str):
    _project_or_404(project_id)
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    body = _body()
    result = tl.auto_assemble(project_id, brief=brief,
                              resolution=body.get("resolution", "1080p"),
                              fps=int(body.get("fps") or 30))
    return jsonify(result)


@studio_bp.route("/api/clips/<clip_id>", methods=["PATCH"])
def update_clip(clip_id: str):
    clip = db.fetch_one("SELECT * FROM timeline_clip WHERE id=?", (clip_id,))
    if not clip:
        return _err("clip not found", 404)
    _project_or_404(clip["project_id"])

    body = _body()
    if "start_s" in body:
        tl.move_clip(clip_id, float(body["start_s"]))
    if any(k in body for k in ("duration_s", "in_s", "out_s")):
        tl.trim_clip(clip_id,
                     duration_s=body.get("duration_s"),
                     in_s=body.get("in_s"), out_s=body.get("out_s"))
    patch = {k: v for k, v in body.items()
             if k in ("volume", "transition_in", "transition_in_s", "text")}
    if patch:
        db.update("timeline_clip", clip_id, patch)
    return jsonify({"clip": db.fetch_one("SELECT * FROM timeline_clip WHERE id=?",
                                         (clip_id,), json_fields=("settings",))})


@studio_bp.route("/api/clips/<clip_id>/split", methods=["POST"])
def split_clip_route(clip_id: str):
    clip = db.fetch_one("SELECT * FROM timeline_clip WHERE id=?", (clip_id,))
    if not clip:
        return _err("clip not found", 404)
    _project_or_404(clip["project_id"])

    at = _body().get("at_s")
    if at is None:
        return _err("at_s is required")
    new_id = tl.split_clip(clip_id, float(at))
    if not new_id:
        return _err("split point is too close to a clip boundary")
    return jsonify({"ok": True, "new_clip_id": new_id}), 201


@studio_bp.route("/api/clips/<clip_id>", methods=["DELETE"])
def delete_clip(clip_id: str):
    clip = db.fetch_one("SELECT project_id FROM timeline_clip WHERE id=?", (clip_id,))
    if not clip:
        return _err("clip not found", 404)
    _project_or_404(clip["project_id"])
    return jsonify({"ok": tl.delete_clip(clip_id)})


@studio_bp.route("/api/tracks/<track_id>", methods=["PATCH"])
def update_track(track_id: str):
    track = db.fetch_one("SELECT * FROM timeline_track WHERE id=?", (track_id,))
    if not track:
        return _err("track not found", 404)
    _project_or_404(track["project_id"])
    body = _body()
    tl.set_track(track_id, muted=body.get("muted"), volume=body.get("volume"))
    return jsonify({"track": db.fetch_one("SELECT * FROM timeline_track WHERE id=?",
                                          (track_id,))})


# =============================================================================
# ASSETS
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/assets")
def list_assets(project_id: str):
    _project_or_404(project_id)
    kind = request.args.get("kind", "")
    sql = "SELECT * FROM media_asset WHERE project_id=?"
    params: tuple = (project_id,)
    if kind:
        sql += " AND kind=?"
        params += (kind,)
    sql += " ORDER BY created_at DESC LIMIT 500"

    storage = get_storage()
    assets = db.fetch_all(sql, params, json_fields=("settings", "meta"))
    for asset in assets:
        asset["url"] = storage.download_url(asset["storage_key"])
        # Report presence honestly — a row is not proof the bytes survived.
        asset["available"] = storage.local_path(asset["storage_key"]) is not None
    return jsonify({"assets": assets, "count": len(assets)})


@studio_bp.route("/api/projects/<project_id>/assets/upload", methods=["POST"])
def upload_asset(project_id: str):
    _project_or_404(project_id)
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return _err("no file supplied")

    data = upload.read()
    if not data:
        return _err("the uploaded file is empty")

    mime = upload.mimetype or "application/octet-stream"
    kind = ("image" if mime.startswith("image/") else
            "video" if mime.startswith("video/") else
            "audio" if mime.startswith("audio/") else "upload")

    duration = None
    if kind == "audio":
        from .providers.voice import measure_duration
        duration = measure_duration(data, mime)

    asset_id = jobs.store_asset(
        project_id=project_id, kind=kind, data=data, mime=mime,
        scene_id=request.form.get("scene_id", ""), source="upload",
        filename=upload.filename[:200], duration_s=duration)

    return jsonify({"asset_id": asset_id, "kind": kind,
                    "duration_s": duration}), 201


@studio_bp.route("/api/assets/<asset_id>", methods=["DELETE"])
def delete_asset(asset_id: str):
    asset = db.fetch_one("SELECT * FROM media_asset WHERE id=?", (asset_id,))
    if not asset:
        return _err("asset not found", 404)
    _project_or_404(asset["project_id"])

    get_storage().delete(asset["storage_key"])
    db.execute("DELETE FROM media_asset WHERE id=?", (asset_id,))
    # Clear references so nothing points at media that no longer exists.
    db.execute("UPDATE scene SET selected_asset_id=NULL, status='pending' "
               "WHERE selected_asset_id=?", (asset_id,))
    db.execute("DELETE FROM timeline_clip WHERE asset_id=?", (asset_id,))
    return jsonify({"ok": True})


@studio_bp.route("/media/<path:key>")
def serve_media(key: str):
    """Serve a stored asset, after verifying the caller owns its project.

    Ownership is re-checked here rather than trusted from the key, because the
    key is guessable and the auth gate alone does not scope by workspace.
    """
    asset = db.fetch_one("SELECT * FROM media_asset WHERE storage_key=?", (key,))
    if not asset:
        return _err("media not found", 404)
    _project_or_404(asset["project_id"])

    path = get_storage().local_path(key)
    if not path or not os.path.exists(path):
        return _err("media is missing from storage", 410)
    return send_file(path, mimetype=asset["mime"], conditional=True)


# =============================================================================
# VISUAL BIBLE
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/references", methods=["GET"])
def list_references(project_id: str):
    _project_or_404(project_id)
    return jsonify({"references": prompts.load_references(project_id)})


@studio_bp.route("/api/projects/<project_id>/references", methods=["POST"])
def create_reference(project_id: str):
    _project_or_404(project_id)
    body = _body()
    name = (body.get("name") or "").strip()
    if not name:
        return _err("a name is required")

    ref_id = db.new_id("vref")
    db.insert("visual_reference", {
        "id": ref_id, "project_id": project_id,
        "kind": body.get("kind") or "character", "name": name[:120],
        "description": body.get("description", ""),
        "attributes": db._dumps(body.get("attributes") or {}),
        "reference_asset_ids": db._dumps(body.get("reference_asset_ids") or []),
        "rights_attested": 1 if body.get("rights_attested") else 0,
        "created_at": db.now(), "updated_at": db.now(),
    })

    # Report what consistency the connected provider can genuinely offer.
    warning = None
    try:
        provider = registry.resolve("image", _workspace())
        warning = prompts.consistency_warning(provider.name, provider)
    except registry.NoProviderAvailable:
        warning = ("No image provider is connected yet, so no consistency "
                   "capability can be confirmed.")

    return jsonify({"reference_id": ref_id, "consistency_warning": warning}), 201


@studio_bp.route("/api/references/<ref_id>", methods=["PATCH", "DELETE"])
def modify_reference(ref_id: str):
    ref = db.fetch_one("SELECT * FROM visual_reference WHERE id=?", (ref_id,))
    if not ref:
        return _err("reference not found", 404)
    _project_or_404(ref["project_id"])

    if request.method == "DELETE":
        db.execute("DELETE FROM visual_reference WHERE id=?", (ref_id,))
        return jsonify({"ok": True})

    body = _body()
    patch = {k: v for k, v in body.items() if k in ("name", "description", "kind")}
    if "attributes" in body:
        patch["attributes"] = db._dumps(body["attributes"])
    if "reference_asset_ids" in body:
        patch["reference_asset_ids"] = db._dumps(body["reference_asset_ids"])
    if "rights_attested" in body:
        patch["rights_attested"] = 1 if body["rights_attested"] else 0
    if not patch:
        return _err("no updatable fields supplied")
    db.update("visual_reference", ref_id, patch)
    return jsonify({"ok": True})


# =============================================================================
# AGENTS: EDITOR, CRITIC, QC
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/editor-insights")
def editor_insights(project_id: str):
    _project_or_404(project_id)
    return jsonify(agents.editor_insights(project_id))


@studio_bp.route("/api/projects/<project_id>/critique", methods=["POST"])
def critique(project_id: str):
    _project_or_404(project_id)
    try:
        review = agents.critique(
            research_report=agents.get_research(project_id),
            script=agents.get_script(project_id),
            storyboard=agents.get_storyboard(project_id))
    except agents.AgentError as exc:
        return _err(str(exc), 502)
    return jsonify(review)


@studio_bp.route("/api/projects/<project_id>/quality-check", methods=["POST"])
def run_quality_check(project_id: str):
    _project_or_404(project_id)
    return jsonify(quality.run(project_id, _workspace()))


# =============================================================================
# YOUTUBE MODE
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/youtube", methods=["POST"])
def youtube_package(project_id: str):
    _project_or_404(project_id)
    script = agents.get_script(project_id)
    if not script:
        return _err("write a script first")
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    try:
        return jsonify(agents.youtube_package(script=script, brief=brief))
    except agents.AgentError as exc:
        return _err(str(exc), 502)


@studio_bp.route("/api/projects/<project_id>/thumbnails", methods=["POST"])
def thumbnail_lab(project_id: str):
    _project_or_404(project_id)
    script = agents.get_script(project_id)
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    try:
        concepts = agents.thumbnail_concepts(
            title=(script or {}).get("title") or brief.get("topic", ""),
            topic=brief.get("topic", ""),
            style=brief.get("visual_style", "cinematic"))
    except agents.AgentError as exc:
        return _err(str(exc), 502)

    # Concepts are text until the user sends one to a provider — no images
    # are generated (or billed) by merely viewing the lab.
    return jsonify({"concepts": concepts,
                    "note": "Select a concept and generate it to create an image."})


@studio_bp.route("/api/projects/<project_id>/thumbnails/generate", methods=["POST"])
def generate_thumbnail(project_id: str):
    _project_or_404(project_id)
    body = _body()
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _err("a generation prompt is required")

    workspace = _workspace()
    registry.resolve("image", workspace, preferred=body.get("provider", ""))
    job = jobs.enqueue(
        project_id=project_id, workspace=workspace, job_type="image",
        prompt=prompt, provider=body.get("provider", ""), owner=_owner(),
        settings={"aspect_ratio": "16:9", "purpose": "thumbnail"})
    return jsonify({"job": job}), 202


# =============================================================================
# MISSIONS
# =============================================================================

@studio_bp.route("/api/projects/<project_id>/mission", methods=["POST"])
def start_mission(project_id: str):
    project = _project_or_404(project_id)
    body = _body()
    stop_after = body.get("stop_after") or "storyboard"
    if stop_after not in pipeline.STAGES:
        return _err(f"unknown stop point '{stop_after}'")

    existing = pipeline.latest(project_id)
    if existing and existing["status"] in ("running", "queued", "awaiting_approval"):
        return _err("a mission is already running for this project", 409,
                    mission_id=existing["id"], status=existing["status"])

    mission = pipeline.create(
        project_id, _workspace(),
        mode=body.get("mode") or project["mode"],
        stop_after=stop_after,
        approval_level=body.get("approval_level") or project["approval_level"])
    return jsonify({"mission": mission}), 202


@studio_bp.route("/api/projects/<project_id>/mission")
def mission_status(project_id: str):
    _project_or_404(project_id)
    return jsonify(pipeline.status(project_id))


@studio_bp.route("/api/missions/<mission_id>/approve", methods=["POST"])
def approve_mission(mission_id: str):
    mission = pipeline.get(mission_id)
    if not mission:
        return _err("mission not found", 404)
    _project_or_404(mission["project_id"])
    body = _body()
    return jsonify(pipeline.approve(mission_id,
                                    approved=body.get("approved", True),
                                    note=body.get("note", "")))


@studio_bp.route("/api/missions/<mission_id>/cancel", methods=["POST"])
def cancel_mission(mission_id: str):
    mission = pipeline.get(mission_id)
    if not mission:
        return _err("mission not found", 404)
    _project_or_404(mission["project_id"])
    return jsonify(pipeline.cancel(mission_id))


# =============================================================================
# RENDER & EXPORT
# =============================================================================

@studio_bp.route("/api/render/capabilities")
def render_capabilities():
    return jsonify(render.export_settings())


@studio_bp.route("/api/projects/<project_id>/render", methods=["POST"])
def start_render(project_id: str):
    _project_or_404(project_id)
    body = _body()

    check = quality.run(project_id, _workspace())
    if not check["passed"] and not body.get("ignore_quality_warnings"):
        return jsonify({
            "error": "quality check found blocking issues",
            "quality": check,
            "hint": "Fix the blocking findings, or resend with "
                    "ignore_quality_warnings=true.",
        }), 409

    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,)) or {}
    result = render.create_job(
        project_id, _workspace(),
        resolution=body.get("resolution", "1080p"),
        fps=int(body.get("fps") or 30),
        fmt=body.get("format", "mp4"),
        aspect_ratio=body.get("aspect_ratio") or brief.get("aspect_ratio", "16:9"),
        burn_captions=bool(body.get("burn_captions")))

    return jsonify(result), (202 if result.get("ok") else 400)


@studio_bp.route("/api/render/<render_job_id>")
def render_status(render_job_id: str):
    job = render.get_job(render_job_id)
    if not job:
        return _err("render job not found", 404)
    _project_or_404(job["project_id"])

    if job["output_key"]:
        job["download_url"] = get_storage().download_url(job["output_key"])
    # Percentages appear only where ffmpeg reported real progress.
    job["progress_is_measured"] = job["progress_pct"] is not None
    job.pop("timeline_json", None)
    return jsonify({"render": job})


@studio_bp.route("/api/render/<render_job_id>/cancel", methods=["POST"])
def cancel_render(render_job_id: str):
    job = render.get_job(render_job_id)
    if not job:
        return _err("render job not found", 404)
    _project_or_404(job["project_id"])
    return jsonify(render.cancel(render_job_id))


@studio_bp.route("/api/projects/<project_id>/renders")
def list_renders(project_id: str):
    _project_or_404(project_id)
    renders = db.fetch_all(
        "SELECT id, status, stage, stage_detail, progress_pct, output_key, "
        "error, created_at, finished_at FROM render_job WHERE project_id=? "
        "ORDER BY created_at DESC LIMIT 20", (project_id,))
    storage = get_storage()
    for row in renders:
        if row["output_key"]:
            row["download_url"] = storage.download_url(row["output_key"])
    return jsonify({"renders": renders})


# =============================================================================
# COST CENTER
# =============================================================================

@studio_bp.route("/api/cost")
def cost_center():
    return jsonify(cost.cost_center(_workspace(), request.args.get("month", "")))


@studio_bp.route("/api/cost/budget", methods=["POST"])
def set_budget():
    body = _body()
    amount = body.get("amount")
    if amount is None:
        return _err("amount is required")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return _err("amount must be a number")
    if amount < 0:
        return _err("amount cannot be negative")
    return jsonify(cost.set_budget(_workspace(), amount, body.get("month", "")))


@studio_bp.route("/api/projects/<project_id>/cost-estimate")
def project_estimate(project_id: str):
    _project_or_404(project_id)
    return jsonify(cost.estimate_project(project_id, _workspace()))


# =============================================================================
# PROVIDER SETTINGS
# =============================================================================

@studio_bp.route("/api/providers")
def list_providers():
    return jsonify(registry.describe_all(_workspace()))


@studio_bp.route("/api/providers/<kind>/<name>", methods=["PATCH"])
def configure_provider(kind: str, name: str):
    """Update provider configuration.

    An `api_key` may be set here but is never returned by any endpoint — it
    is stored server-side and redacted from every read.
    """
    body = _body()
    settings = body.get("settings") if isinstance(body.get("settings"), dict) else {}
    if body.get("api_key"):
        settings = {**settings, "api_key": str(body["api_key"])}

    try:
        cfg = registry.set_config(
            _workspace(), kind, name,
            enabled=body.get("enabled"),
            default_model=body.get("default_model"),
            settings=settings or None)
    except ValueError as exc:
        return _err(str(exc), 404)

    return jsonify({"provider": name, "kind": kind,
                    "enabled": cfg["enabled"],
                    "default_model": cfg["default_model"],
                    "note": "Credentials are stored server-side and are never "
                            "returned by the API."})


@studio_bp.route("/api/providers/<kind>/<name>/verify", methods=["POST"])
def verify_provider(kind: str, name: str):
    """Make a real call to confirm the provider works with these credentials."""
    try:
        return jsonify(registry.verify(kind, name, _workspace()))
    except ValueError as exc:
        return _err(str(exc), 404)


@studio_bp.route("/api/storage")
def storage_info():
    from .storage import describe_storage
    return jsonify(describe_storage())


@studio_bp.route("/api/health")
def health():
    from .storage import describe_storage
    return jsonify({
        "ok": True,
        "workers": jobs.worker_status(),
        "render": render.probe(),
        "storage": describe_storage(),
    })


# =============================================================================
# STARTUP
# =============================================================================

def init_studio() -> dict:
    """Initialise the Studio subsystem. Called once from app.py."""
    db.init_db()
    handlers.register_all()
    requeued = jobs.recover_orphans()
    workers = jobs.start_workers()
    return {"workers": workers, "requeued_jobs": requeued,
            "render_available": render.probe()["available"]}
