"""
studio/quality.py — 🔍 Quality Control Agent.

Runs before rendering and inspects **real project state** — asset rows,
measured durations, storage presence, caption coverage. Every finding is
derived from something checkable, so each one comes with the numbers behind
it and a specific recommendation.

This is deliberately not an LLM call. "Scene 7 is 2.4s shorter than its
narration" is arithmetic; asking a model to guess at it would be slower, less
reliable, and unverifiable. The Critic agent handles the subjective review
(is the hook good?); QC handles the mechanical one (will this render?).

Severities:
    blocking  the render will fail or produce something broken
    warning   the render will succeed but the result has a real defect
    note      worth knowing, not a defect
"""

from __future__ import annotations

from typing import Optional

from . import captions, db, render, timeline as tl
from .storage import get_storage


def _finding(severity: str, code: str, message: str,
             recommendation: str = "", scene_idx: Optional[int] = None,
             **extra) -> dict:
    return {"severity": severity, "code": code, "message": message,
            "recommendation": recommendation, "scene": scene_idx, **extra}


def run(project_id: str, workspace: str = "default") -> dict:
    """Full pre-render inspection."""
    findings: list[dict] = []

    scenes = db.fetch_all(
        """SELECT s.* FROM scene s JOIN storyboard b ON b.id = s.storyboard_id
           WHERE s.project_id=? AND b.is_current=1 ORDER BY s.idx""",
        (project_id,))
    timeline = tl.load(project_id)

    findings += _check_scenes(project_id, scenes)
    findings += _check_timeline(timeline)
    findings += _check_assets(project_id, timeline)
    findings += _check_audio(project_id, scenes)
    findings += _check_captions(project_id, timeline)
    findings += _check_resolution(timeline)
    findings += _check_render_capability()
    findings += _check_rights(project_id)

    blocking = sum(1 for f in findings if f["severity"] == "blocking")
    warnings = sum(1 for f in findings if f["severity"] == "warning")

    if not findings:
        findings.append(_finding("note", "all_clear",
                                 "No problems found. The project is ready to render."))

    check_id = db.new_id("qc")
    db.insert("quality_check", {
        "id": check_id, "project_id": project_id,
        "passed": 1 if blocking == 0 else 0,
        "blocking_count": blocking, "warning_count": warnings,
        "findings": db._dumps(findings), "created_at": db.now(),
    })

    return {
        "id": check_id,
        "passed": blocking == 0,
        "blocking_count": blocking,
        "warning_count": warnings,
        "findings": findings,
        "summary": _summarise(blocking, warnings, len(findings)),
    }


def _summarise(blocking: int, warnings: int, total: int) -> str:
    if blocking:
        return (f"{blocking} blocking issue(s) must be fixed before rendering"
                + (f", plus {warnings} warning(s)" if warnings else "") + ".")
    if warnings:
        return f"Ready to render, with {warnings} warning(s) worth reviewing."
    return "Ready to render." if total <= 1 else "Ready to render."


# =============================================================================
# CHECKS
# =============================================================================

def _check_scenes(project_id: str, scenes: list[dict]) -> list[dict]:
    if not scenes:
        return [_finding("blocking", "no_storyboard",
                         "This project has no storyboard.",
                         "Generate a script, then a storyboard, before rendering.")]

    findings = []
    missing = [s for s in scenes if not s["selected_asset_id"]]
    failed = [s for s in scenes if s["status"] == "failed"]

    if missing:
        idxs = ", ".join(str(s["idx"] + 1) for s in missing[:10])
        findings.append(_finding(
            "blocking", "missing_scene_assets",
            f"{len(missing)} of {len(scenes)} scenes have no generated asset "
            f"(scene {idxs}).",
            "Generate the missing scenes, or set them to a stock or uploaded "
            "asset. Scenes without assets leave gaps in the render."))

    for scene in failed:
        findings.append(_finding(
            "warning", "scene_generation_failed",
            f"Scene {scene['idx'] + 1} failed to generate: "
            f"{scene['error'][:160] or 'no error recorded'}",
            "Retry it, edit the prompt, switch provider, or skip the scene.",
            scene_idx=scene["idx"]))

    for scene in scenes:
        if scene["duration_s"] < 0.5:
            findings.append(_finding(
                "blocking", "scene_too_short",
                f"Scene {scene['idx'] + 1} is {scene['duration_s']:.2f}s long.",
                "Extend it to at least 0.5s or merge it into a neighbour.",
                scene_idx=scene["idx"]))
    return findings


def _check_timeline(timeline: Optional[dict]) -> list[dict]:
    if not timeline:
        return [_finding("blocking", "no_timeline",
                         "No timeline has been assembled.",
                         "Run Auto Assemble to build an editable draft timeline.")]

    video_track = next((t for t in timeline["tracks"] if t["kind"] == "video"), None)
    if not video_track or not video_track["clips"]:
        return [_finding("blocking", "empty_timeline",
                         "The timeline has no video clips.",
                         "Run Auto Assemble after generating scene assets.")]

    findings = []
    clips = sorted(video_track["clips"], key=lambda c: c["start_s"])
    cursor = 0.0
    for clip in clips:
        if clip["start_s"] - cursor > 0.5:
            findings.append(_finding(
                "warning", "timeline_gap",
                f"A {clip['start_s'] - cursor:.1f}s gap sits at "
                f"{cursor:.1f}s with no video.",
                "The render will show black there. Extend the previous clip "
                "or drop in a scene to cover it."))
        cursor = max(cursor, clip["start_s"] + clip["duration_s"])

    if timeline["duration_s"] < 1:
        findings.append(_finding("blocking", "zero_duration",
                                 "The timeline is effectively zero-length.",
                                 "Add clips before rendering."))
    return findings


def _check_assets(project_id: str, timeline: Optional[dict]) -> list[dict]:
    """Confirm every referenced asset is really in storage.

    A DB row is not proof the bytes exist — this catches media deleted or
    lost between generation and render, which would otherwise fail the encode
    minutes in.
    """
    if not timeline:
        return []

    storage = get_storage()
    findings, broken = [], []

    for track in timeline["tracks"]:
        for clip in track["clips"]:
            if clip.get("missing_asset"):
                broken.append(f"{track['kind']} clip at {clip['start_s']:.1f}s "
                              f"(asset record deleted)")
                continue
            asset = clip.get("asset")
            if asset and not storage.local_path(asset["storage_key"]):
                broken.append(f"{track['kind']} clip at {clip['start_s']:.1f}s "
                              f"({asset['filename']} missing from storage)")

    if broken:
        findings.append(_finding(
            "blocking", "broken_assets",
            f"{len(broken)} clip(s) reference media that is not in storage: "
            f"{'; '.join(broken[:5])}",
            "Regenerate or re-upload the missing media, then re-assemble."))
    return findings


def _check_audio(project_id: str, scenes: list[dict]) -> list[dict]:
    findings = []

    voiceovers = db.fetch_all(
        "SELECT scene_id, duration_s, status FROM voiceover WHERE project_id=?",
        (project_id,))
    if not voiceovers:
        findings.append(_finding(
            "warning", "no_voiceover",
            "No voiceover has been generated — the video will be silent "
            "unless that is intentional.",
            "Generate narration under Voice, or add a music track."))
        return findings

    by_scene = {v["scene_id"]: v for v in voiceovers if v["scene_id"]}
    missing = [s for s in scenes if s["id"] not in by_scene]
    if missing:
        findings.append(_finding(
            "warning", "partial_voiceover",
            f"{len(missing)} scene(s) have no narration audio.",
            "Generate the missing segments, or accept silence over those shots."))

    # The timing check the spec is explicit about.
    timing = tl.analyse_timing(project_id)
    for conflict in timing["conflicts"]:
        severity = "warning" if abs(conflict["delta_s"]) < 3 else "blocking"
        findings.append(_finding(
            severity, "duration_mismatch", conflict["message"],
            f"Recommendation: extend Scene {conflict['scene_idx'] + 1} by "
            f"{conflict['delta_s']:.1f}s, or shorten its narration."
            if conflict["delta_s"] > 0 else
            f"Recommendation: shorten Scene {conflict['scene_idx'] + 1} by "
            f"{abs(conflict['delta_s']):.1f}s to remove the silent tail.",
            scene_idx=conflict["scene_idx"],
            planned_s=conflict["planned_s"],
            narration_s=conflict["narration_s"]))

    if timing["unknown"]:
        findings.append(_finding(
            "note", "unmeasured_timing",
            f"{len(timing['unknown'])} scene(s) have no measured narration "
            f"duration, so their timing could not be checked.",
            "Generate their voiceovers to verify synchronisation."))
    return findings


def _check_captions(project_id: str, timeline: Optional[dict]) -> list[dict]:
    track = captions.get_track(project_id)
    if not track:
        return [_finding("note", "no_captions",
                         "No caption track has been generated.",
                         "Generate captions — most platforms reward them.")]

    findings = []
    cues = track.get("cues") or []
    if not cues:
        return [_finding("warning", "empty_captions",
                         "The caption track exists but has no cues.",
                         "Regenerate captions from the script or voiceover.")]

    if track["timing_source"] == "script":
        findings.append(_finding(
            "warning", "caption_timing_approximate",
            "Captions are timed from the planned script, not from the "
            "generated audio.",
            "Regenerate captions after voice generation so they follow the "
            "narration that was actually produced."))

    duration = timeline["duration_s"] if timeline else 0
    if duration:
        gaps = captions.find_gaps(cues, duration)
        if gaps:
            longest = max(gaps, key=lambda g: g["duration_s"])
            findings.append(_finding(
                "note", "caption_gaps",
                f"{len(gaps)} stretch(es) have no captions; the longest is "
                f"{longest['duration_s']:.1f}s at {longest['start_s']:.1f}s.",
                "Fine if those passages have no narration — otherwise add cues."))
    return findings


def _check_resolution(timeline: Optional[dict]) -> list[dict]:
    """Flag source media below the canvas — upscaling looks soft."""
    if not timeline:
        return []

    findings, undersized = [], []
    for track in timeline["tracks"]:
        if track["kind"] != "video":
            continue
        for clip in track["clips"]:
            asset = clip.get("asset")
            if not asset or not asset.get("width") or not asset.get("height"):
                continue
            if asset["width"] < timeline["width"] * 0.75:
                undersized.append(
                    f"{asset['filename']} ({asset['width']}×{asset['height']})")

    if undersized:
        findings.append(_finding(
            "warning", "resolution_mismatch",
            f"{len(undersized)} asset(s) are smaller than the "
            f"{timeline['width']}×{timeline['height']} canvas: "
            f"{', '.join(undersized[:4])}",
            "They will be upscaled and look soft. Regenerate at a higher "
            "resolution, or render at a smaller output size."))
    return findings


def _check_render_capability() -> list[dict]:
    capability = render.probe()
    if capability["available"]:
        return []
    return [_finding("blocking", "no_renderer", capability["reason"],
                     capability["remedy"])]


def _check_rights(project_id: str) -> list[dict]:
    """Surface music with unverified rights before it is baked into a render."""
    tracks = db.fetch_all(
        "SELECT title, rights_status FROM music_track "
        "WHERE project_id=? AND asset_id IS NOT NULL", (project_id,))
    unverified = [t for t in tracks if t["rights_status"] == "unverified"]
    if not unverified:
        return []
    return [_finding(
        "warning", "unverified_music_rights",
        f"{len(unverified)} music track(s) have no rights confirmation: "
        f"{', '.join(t['title'] or 'untitled' for t in unverified[:3])}",
        "Confirm you hold the rights to use this music before publishing. "
        "Rendering it does not grant you a licence.")]


def latest(project_id: str) -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM quality_check WHERE project_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (project_id,), json_fields=("findings",))
