"""
studio/pipeline.py — Mission orchestration.

A *mission* runs the production pipeline for one project:

    RESEARCH → SCRIPT → STORYBOARD → CRITIC → VISUALS → VOICE
             → ASSEMBLE → QUALITY → (RENDER)

Three things make this more than a for-loop:

**Stop points.** `stop_after` lets a mission end at any stage — research
only, script only, storyboard only, visuals only, or the full pipeline.

**Approval gates.** `approval_level` decides where the mission pauses for a
human: never (`full_auto`), before anything that costs money (`expensive`),
or between every stage (`manual`). A paused mission sets `awaiting` and stops
cleanly; `approve()` resumes it. Budget refusals pause rather than fail, so
raising the budget resumes rather than restarts.

**Partial failure is normal.** A scene that fails does not fail the mission.
Asset generation waits for all scene jobs, then continues with what
succeeded, recording which scenes are missing. A stage that produces nothing
usable stops the mission with a reason — but never rolls back what earlier
stages produced.

Every stage writes to editable project tables, so a mission that stops
halfway leaves a usable project, not a wreck.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import (agents, captions, cost, db, jobs, quality, render,
               timeline as tl)
from .providers import registry
from .providers.base import GenerationRequest, JobState

#: Ordered pipeline. `stop_after` names one of these.
STAGES = ["research", "script", "storyboard", "critic", "visuals", "voice",
          "assemble", "quality", "render"]

STAGE_LABELS = {
    "research": "🧠 Researching",
    "script": "✍️ Writing script",
    "storyboard": "🎬 Creating storyboard",
    "critic": "🔍 Reviewing before generation",
    "visuals": "🎨 Generating visuals",
    "voice": "🎙️ Voice generation",
    "assemble": "✂️ Editing",
    "quality": "✅ Quality check",
    "render": "📤 Rendering",
}

#: Stages that spend money at a provider. These are what `expensive` gates.
PAID_STAGES = {"visuals", "voice"}

APPROVAL_LEVELS = ("full_auto", "expensive", "manual")


# =============================================================================
# MISSION LIFECYCLE
# =============================================================================

def create(project_id: str, workspace: str, *, mode: str = "assisted",
           stop_after: str = "storyboard",
           approval_level: str = "expensive") -> dict:
    if stop_after not in STAGES:
        raise ValueError(f"unknown stop point '{stop_after}'")
    if approval_level not in APPROVAL_LEVELS:
        raise ValueError(f"unknown approval level '{approval_level}'")

    stop_index = STAGES.index(stop_after)
    planned = [
        {"stage": s, "label": STAGE_LABELS[s], "status": "waiting",
         "detail": "", "started_at": None, "finished_at": None}
        for s in STAGES[:stop_index + 1]
    ]

    mission_id = db.new_id("msn")
    db.insert("studio_mission", {
        "id": mission_id, "project_id": project_id, "workspace": workspace,
        "mode": mode, "stop_after": stop_after, "status": "queued",
        "current_stage": "", "stages": db._dumps(planned), "awaiting": "",
        "created_at": db.now(), "updated_at": db.now(),
    })
    db.touch_project(project_id, status="in_progress", approval_level=approval_level,
                     mode=mode)

    thread = threading.Thread(target=_run, args=(mission_id,),
                              name=f"studio-mission-{mission_id[:8]}", daemon=True)
    thread.start()
    return get(mission_id)


def get(mission_id: str) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM studio_mission WHERE id=?", (mission_id,),
                        json_fields=("stages",))


def latest(project_id: str) -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM studio_mission WHERE project_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (project_id,), json_fields=("stages",))


def cancel(mission_id: str) -> dict:
    mission = get(mission_id)
    if not mission:
        return {"ok": False, "error": "mission not found"}
    if mission["status"] in ("completed", "failed", "cancelled"):
        return {"ok": False, "error": f"mission already {mission['status']}"}

    db.update("studio_mission", mission_id, {"cancel_requested": 1})
    # Stop the in-flight provider work too, so cancelling actually saves money.
    for job in db.fetch_all(
            "SELECT id FROM generation_job WHERE project_id=? AND status IN (?,?,?,?)",
            (mission["project_id"], JobState.QUEUED.value, JobState.PREPARING.value,
             JobState.GENERATING.value, JobState.PROCESSING.value)):
        jobs.cancel_job(job["id"])
    return {"ok": True, "note": "mission cancellation requested"}


def approve(mission_id: str, *, approved: bool = True,
            note: str = "") -> dict:
    """Resume a mission paused at an approval gate."""
    mission = get(mission_id)
    if not mission:
        return {"ok": False, "error": "mission not found"}
    if mission["status"] != "awaiting_approval":
        return {"ok": False,
                "error": f"mission is {mission['status']}, not awaiting approval"}

    if not approved:
        db.update("studio_mission", mission_id, {
            "status": "cancelled", "awaiting": "",
            "error": f"declined at {mission['current_stage']}"
                     + (f": {note}" if note else "")})
        return {"ok": True, "resumed": False, "note": "mission stopped as declined"}

    db.update("studio_mission", mission_id,
              {"status": "running", "awaiting": ""})
    thread = threading.Thread(target=_run, args=(mission_id,),
                              name=f"studio-mission-{mission_id[:8]}", daemon=True)
    thread.start()
    return {"ok": True, "resumed": True}


# =============================================================================
# STAGE BOOKKEEPING
# =============================================================================

def _stage_index(stages: list[dict], name: str) -> int:
    for i, stage in enumerate(stages):
        if stage["stage"] == name:
            return i
    return -1


def _set_stage(mission_id: str, name: str, status: str, detail: str = "") -> None:
    mission = get(mission_id)
    if not mission:
        return
    stages = mission["stages"] or []
    idx = _stage_index(stages, name)
    if idx >= 0:
        stages[idx]["status"] = status
        if detail:
            stages[idx]["detail"] = detail
        if status == "running" and not stages[idx]["started_at"]:
            stages[idx]["started_at"] = db.now()
        if status in ("complete", "failed", "skipped"):
            stages[idx]["finished_at"] = db.now()
    db.update("studio_mission", mission_id,
              {"stages": db._dumps(stages), "current_stage": name})


def _cancelled(mission_id: str) -> bool:
    row = db.fetch_one("SELECT cancel_requested FROM studio_mission WHERE id=?",
                       (mission_id,))
    return bool(row and row["cancel_requested"])


def _pause_for_approval(mission_id: str, stage: str, reason: str,
                        context: Optional[dict] = None) -> None:
    db.update("studio_mission", mission_id, {
        "status": "awaiting_approval",
        "awaiting": db._dumps({"stage": stage, "reason": reason,
                               "context": context or {}}),
        "current_stage": stage,
    })
    _set_stage(mission_id, stage, "awaiting_approval", reason)


def _needs_approval(approval_level: str, stage: str) -> bool:
    if approval_level == "manual":
        return True
    if approval_level == "expensive":
        return stage in PAID_STAGES
    return False


# =============================================================================
# RUNNER
# =============================================================================

def _run(mission_id: str) -> None:
    mission = get(mission_id)
    if not mission:
        return

    project_id = mission["project_id"]
    workspace = mission["workspace"]
    project = db.fetch_one("SELECT * FROM studio_project WHERE id=?", (project_id,))
    if not project:
        db.update("studio_mission", mission_id,
                  {"status": "failed", "error": "project not found"})
        return

    approval_level = project["approval_level"]
    db.update("studio_mission", mission_id, {"status": "running"})

    stop_index = STAGES.index(mission["stop_after"])
    stages = mission["stages"] or []

    try:
        for stage in STAGES[:stop_index + 1]:
            if _cancelled(mission_id):
                db.update("studio_mission", mission_id,
                          {"status": "cancelled", "current_stage": stage})
                _set_stage(mission_id, stage, "skipped", "mission cancelled")
                return

            idx = _stage_index(stages, stage)
            if idx >= 0 and stages[idx]["status"] == "complete":
                continue  # already done before an approval pause

            # Approval gate, checked before the stage runs.
            if _needs_approval(approval_level, stage):
                mission = get(mission_id)
                stages = mission["stages"] or []
                idx = _stage_index(stages, stage)
                if idx >= 0 and stages[idx]["status"] != "approved":
                    context = _approval_context(project_id, workspace, stage)
                    _pause_for_approval(
                        mission_id, stage,
                        f"{STAGE_LABELS[stage]} needs your approval", context)
                    return

            _set_stage(mission_id, stage, "running")
            handler = _HANDLERS[stage]
            result = handler(project_id, workspace, project)

            if result.get("halt"):
                _set_stage(mission_id, stage, "failed", result.get("detail", ""))
                db.update("studio_mission", mission_id, {
                    "status": "failed",
                    "error": result.get("detail", f"{stage} produced nothing usable")})
                return

            _set_stage(mission_id, stage,
                       "skipped" if result.get("skipped") else "complete",
                       result.get("detail", ""))

            mission = get(mission_id)
            stages = mission["stages"] or []

        db.update("studio_mission", mission_id,
                  {"status": "completed", "current_stage": mission["stop_after"]})
        db.touch_project(project_id, status="ready", stage=mission["stop_after"])

    except Exception as exc:  # noqa: BLE001 - a mission must fail visibly
        current = (get(mission_id) or {}).get("current_stage", "")
        if current:
            _set_stage(mission_id, current, "failed", str(exc)[:300])
        db.update("studio_mission", mission_id,
                  {"status": "failed", "error": f"{current}: {exc}"[:1000]})


def _approval_context(project_id: str, workspace: str, stage: str) -> dict:
    """What the user needs to decide — for paid stages, the money."""
    if stage not in PAID_STAGES:
        return {}
    estimate = cost.estimate_project(project_id, workspace)
    budget = cost.get_budget(workspace)
    return {
        "cost_estimate": estimate,
        "budget": budget,
        "disclaimer": ("This is an estimate, not a guaranteed price. Actual "
                       "charges come from your providers."),
    }


# =============================================================================
# STAGE HANDLERS
# =============================================================================

def _stage_research(project_id: str, workspace: str, project: dict) -> dict:
    brief = _get_brief(project_id)
    if not brief:
        return {"halt": True, "detail": "no brief — cannot research"}
    report = agents.research(project_id, brief["topic"] or project["idea"],
                             audience=brief["audience"])
    return {"detail": f"{len(report['key_points'])} key points, "
                      f"{len(report['sources'])} source(s), "
                      f"evidence: {report['evidence_mode']}"}


def _stage_script(project_id: str, workspace: str, project: dict) -> dict:
    brief = _get_brief(project_id)
    if not brief:
        return {"halt": True, "detail": "no brief — cannot write a script"}
    research = agents.get_research(project_id)
    script = agents.write_script(project_id, brief=brief, research_report=research)
    agents.save_script(project_id, script)
    return {"detail": f"{len(script['segments'])} segments, "
                      f"{script['word_count']} words"}


def _stage_storyboard(project_id: str, workspace: str, project: dict) -> dict:
    brief = _get_brief(project_id)
    script = agents.get_script(project_id)
    if not script:
        return {"halt": True, "detail": "no script to build a storyboard from"}
    board = agents.direct(project_id, brief=brief, script=script)
    agents.save_storyboard(project_id, board, brief=brief, workspace=workspace)
    video_count = sum(1 for s in board["scenes"] if s["asset_type"] == "ai_video")
    return {"detail": f"{len(board['scenes'])} scenes "
                      f"({video_count} video, {len(board['scenes']) - video_count} still)"}


def _stage_critic(project_id: str, workspace: str, project: dict) -> dict:
    """Review before money is spent. Findings never block automatically —
    the user decides — but they are recorded where the UI shows them."""
    try:
        review = agents.critique(
            research_report=agents.get_research(project_id),
            script=agents.get_script(project_id),
            storyboard=agents.get_storyboard(project_id))
    except agents.AgentError as exc:
        return {"skipped": True, "detail": f"critic unavailable: {exc}"}

    board = agents.get_storyboard(project_id)
    if board:
        db.update("storyboard", board["id"],
                  {"notes": db._dumps(review)})
    return {"detail": f"verdict: {review['verdict']}, score {review['score']}/10, "
                      f"{review['blocking']} blocking finding(s)"}


def _stage_visuals(project_id: str, workspace: str, project: dict) -> dict:
    """Generate scene assets, tolerating individual failures."""
    board = agents.get_storyboard(project_id)
    if not board or not board.get("scenes"):
        return {"halt": True, "detail": "no storyboard to generate visuals for"}

    brief = _get_brief(project_id)
    pending = [s for s in board["scenes"]
               if not s["selected_asset_id"]
               and s["asset_type"] in ("ai_image", "ai_video")]

    if not pending:
        return {"skipped": True, "detail": "every scene already has an asset"}

    queued, blocked = [], []
    for scene in pending:
        kind = "video" if scene["asset_type"] == "ai_video" else "image"
        try:
            registry.resolve(kind, workspace)
        except registry.NoProviderAvailable as exc:
            blocked.append((scene, exc.message))
            continue

        job = jobs.enqueue(
            project_id=project_id, workspace=workspace,
            job_type=kind, scene_id=scene["id"],
            prompt=scene["generation_prompt"] or scene["visual_description"],
            settings={"aspect_ratio": brief.get("aspect_ratio", "16:9"),
                      "negative_prompt": scene["negative_prompt"],
                      "duration_s": scene["duration_s"]},
            idempotency_key=f"{project_id}:{scene['id']}:{kind}:v{board['version']}",
        )
        queued.append(job["id"])
        db.update("scene", scene["id"], {"status": "queued"})

    for scene, reason in blocked:
        db.update("scene", scene["id"],
                  {"status": "blocked", "error": reason[:500]})

    if not queued:
        return {"halt": True,
                "detail": f"no connected provider for any scene "
                          f"({blocked[0][1] if blocked else 'unknown reason'})"}

    completed, failed = _await_jobs(project_id, queued)

    detail = f"{completed} generated, {failed} failed"
    if blocked:
        detail += f", {len(blocked)} blocked (no provider)"
    # Partial success is success: the pipeline continues around the holes.
    return {"detail": detail}


def _stage_voice(project_id: str, workspace: str, project: dict) -> dict:
    board = agents.get_storyboard(project_id)
    if not board or not board.get("scenes"):
        return {"skipped": True, "detail": "no scenes to narrate"}

    brief = _get_brief(project_id)
    try:
        registry.resolve("voice", workspace)
    except registry.NoProviderAvailable as exc:
        return {"skipped": True, "detail": f"skipped — {exc.message}"}

    # No voice is pinned at project level, so the handler picks the first
    # voice the connected provider actually offers.
    queued = []
    for scene in board["scenes"]:
        if not scene["narration"].strip():
            continue
        existing = db.fetch_one(
            "SELECT id, asset_id FROM voiceover WHERE scene_id=? AND project_id=?",
            (scene["id"], project_id))
        if existing and existing["asset_id"]:
            continue

        job = jobs.enqueue(
            project_id=project_id, workspace=workspace, job_type="voice",
            scene_id=scene["id"], prompt=scene["narration"],
            settings={"language": brief.get("language", "en"),
                      "voice_id": "", "speed": 1.0},
            idempotency_key=f"{project_id}:{scene['id']}:voice:v{board['version']}",
        )
        queued.append(job["id"])

    if not queued:
        return {"skipped": True, "detail": "narration already generated"}

    completed, failed = _await_jobs(project_id, queued)
    return {"detail": f"{completed} narrated, {failed} failed"}


def _stage_assemble(project_id: str, workspace: str, project: dict) -> dict:
    brief = _get_brief(project_id)

    captions.save_track(project_id, style="minimal",
                        language=brief.get("language", "en"))

    result = tl.auto_assemble(project_id, brief=brief)
    if not result["scenes_placed"]:
        return {"halt": True,
                "detail": "no scenes had assets to place on the timeline"}

    detail = f"{result['scenes_placed']} clips over {result['duration_s']:.1f}s"
    if result["scenes_skipped"]:
        detail += f", {result['scenes_skipped']} scene(s) left as gaps"
    return {"detail": detail}


def _stage_quality(project_id: str, workspace: str, project: dict) -> dict:
    report = quality.run(project_id, workspace)
    return {"detail": report["summary"]}


def _stage_render(project_id: str, workspace: str, project: dict) -> dict:
    check = quality.latest(project_id)
    if check and check["blocking_count"]:
        return {"halt": True,
                "detail": f"quality check found {check['blocking_count']} blocking "
                          f"issue(s); fix them before rendering"}

    brief = _get_brief(project_id)
    result = render.create_job(project_id, workspace,
                               aspect_ratio=brief.get("aspect_ratio", "16:9"))
    if not result.get("ok"):
        return {"halt": True, "detail": result.get("error", "render refused")}

    job_id = result["render_job_id"]
    deadline = time.time() + 60 * 60
    while time.time() < deadline:
        job = render.get_job(job_id)
        if not job:
            return {"halt": True, "detail": "render job disappeared"}
        if job["status"] == "completed":
            return {"detail": "render complete"}
        if job["status"] in ("failed", "cancelled"):
            return {"halt": True,
                    "detail": job["error"] or f"render {job['status']}"}
        time.sleep(3)
    return {"halt": True, "detail": "render exceeded its time limit"}


_HANDLERS = {
    "research": _stage_research,
    "script": _stage_script,
    "storyboard": _stage_storyboard,
    "critic": _stage_critic,
    "visuals": _stage_visuals,
    "voice": _stage_voice,
    "assemble": _stage_assemble,
    "quality": _stage_quality,
    "render": _stage_render,
}


# =============================================================================
# HELPERS
# =============================================================================

def _get_brief(project_id: str) -> dict:
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (project_id,))
    return brief or {}


def _await_jobs(project_id: str, job_ids: list[str],
                timeout_s: int = 60 * 45) -> tuple[int, int]:
    """Wait for a batch of generation jobs, tolerating individual failures.

    Returns (completed, failed). A failure here is a per-scene outcome, not a
    mission-level one — that is what keeps one bad scene from killing an
    18-scene video.
    """
    deadline = time.time() + timeout_s
    pending = set(job_ids)
    completed = failed = 0

    while pending and time.time() < deadline:
        for job_id in list(pending):
            job = jobs.get_job(job_id)
            if not job:
                pending.discard(job_id)
                failed += 1
                continue
            if job["status"] == JobState.COMPLETED.value:
                pending.discard(job_id)
                completed += 1
            elif job["status"] in (JobState.FAILED.value, JobState.CANCELLED.value):
                pending.discard(job_id)
                failed += 1
        if pending:
            time.sleep(2)

    failed += len(pending)  # anything still pending has timed out
    return completed, failed


def status(project_id: str) -> dict:
    """Mission view for the UI — the progress panel from the spec."""
    mission = latest(project_id)
    if not mission:
        return {"mission": None}

    stages = mission["stages"] or []
    for stage in stages:
        if stage["stage"] == "visuals" and stage["status"] == "running":
            done = db.fetch_one(
                """SELECT COUNT(*) AS n FROM scene s
                   JOIN storyboard b ON b.id = s.storyboard_id
                   WHERE s.project_id=? AND b.is_current=1 AND s.status='completed'""",
                (project_id,))
            total = db.fetch_one(
                """SELECT COUNT(*) AS n FROM scene s
                   JOIN storyboard b ON b.id = s.storyboard_id
                   WHERE s.project_id=? AND b.is_current=1""", (project_id,))
            # A real count of finished scenes — not a synthetic percentage.
            stage["detail"] = (f"Scene {(done or {}).get('n', 0)} of "
                               f"{(total or {}).get('n', 0)}")

    return {
        "mission": {
            "id": mission["id"],
            "status": mission["status"],
            "mode": mission["mode"],
            "stop_after": mission["stop_after"],
            "current_stage": mission["current_stage"],
            "error": mission["error"],
            "awaiting": db._loads(mission["awaiting"], None),
            "stages": stages,
        }
    }
