"""
studio/timeline.py — Timeline model, auto-assembly, and the voice timing engine.

The timeline is the editable draft the whole pipeline converges on: four
track kinds (video, voice, music, caption) holding clips that reference real
media assets. It is plain data, so the renderer, the editor UI, and the
quality checker all read the same structure.

The voice timing engine
-----------------------
This is the part the spec is most emphatic about. A scene planned at 8
seconds whose narration actually takes 10.4 seconds is a real conflict, and
there are only bad ways to hide it: stretching the audio distorts the voice,
truncating it cuts words off, and silently letting the scene overrun
desynchronises everything after it.

So `analyse_timing()` **detects and reports** the mismatch with the real
measured durations, and offers the four resolutions the spec lists. It never
picks one silently. `apply_timing_resolution()` acts only on an explicit
choice. Where narration duration is unknown (no voiceover generated yet) it
says "unknown" rather than assuming the planned value is correct.
"""

from __future__ import annotations

from typing import Optional

from . import db

TRACK_KINDS = ("video", "voice", "music", "caption")

#: Below this, a timing difference is not worth interrupting the user about.
TIMING_TOLERANCE_S = 0.35


# =============================================================================
# TIMELINE CRUD
# =============================================================================

def _dimensions(aspect_ratio: str, resolution: str = "1080p") -> tuple[int, int]:
    heights = {"720p": 720, "1080p": 1080, "4k": 2160}
    height = heights.get(resolution.lower(), 1080)
    if aspect_ratio == "9:16":
        return int(height * 9 / 16) // 2 * 2, height
    if aspect_ratio == "1:1":
        return height, height
    return int(height * 16 / 9) // 2 * 2, height


def get_or_create(project_id: str, *, aspect_ratio: str = "16:9",
                  fps: int = 30, resolution: str = "1080p") -> dict:
    existing = db.fetch_one("SELECT * FROM timeline WHERE project_id=?", (project_id,))
    if existing:
        return existing

    width, height = _dimensions(aspect_ratio, resolution)
    timeline_id = db.new_id("tl")
    db.insert("timeline", {
        "id": timeline_id, "project_id": project_id, "fps": fps,
        "width": width, "height": height, "aspect_ratio": aspect_ratio,
        "duration_s": 0, "created_at": db.now(), "updated_at": db.now(),
    })
    for idx, kind in enumerate(TRACK_KINDS):
        db.insert("timeline_track", {
            "id": db.new_id("trk"), "timeline_id": timeline_id,
            "project_id": project_id, "kind": kind,
            "label": kind.capitalize(), "idx": idx,
            "muted": 0, "volume": 1.0, "locked": 0,
        })
    return db.fetch_one("SELECT * FROM timeline WHERE id=?", (timeline_id,))


def load(project_id: str) -> Optional[dict]:
    """Full timeline with tracks, clips, and resolved asset references."""
    timeline = db.fetch_one("SELECT * FROM timeline WHERE project_id=?", (project_id,))
    if not timeline:
        return None

    tracks = db.fetch_all(
        "SELECT * FROM timeline_track WHERE timeline_id=? ORDER BY idx",
        (timeline["id"],))

    assets = {
        a["id"]: a for a in db.fetch_all(
            "SELECT id, kind, storage_key, mime, duration_s, width, height, "
            "filename, provider FROM media_asset WHERE project_id=?", (project_id,))
    }

    for track in tracks:
        clips = db.fetch_all(
            "SELECT * FROM timeline_clip WHERE track_id=? ORDER BY start_s",
            (track["id"],), json_fields=("settings",))
        for clip in clips:
            asset = assets.get(clip["asset_id"]) if clip["asset_id"] else None
            clip["asset"] = asset
            # A clip whose asset row vanished is broken, and the QC agent
            # must be able to see that rather than infer it from a null.
            clip["missing_asset"] = bool(clip["asset_id"] and asset is None)
        track["clips"] = clips

    timeline["tracks"] = tracks
    timeline["duration_s"] = compute_duration(timeline)
    return timeline


def compute_duration(timeline: dict) -> float:
    end = 0.0
    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            end = max(end, clip["start_s"] + clip["duration_s"])
    return round(end, 3)


def _track(timeline_id: str, kind: str) -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM timeline_track WHERE timeline_id=? AND kind=?",
        (timeline_id, kind))


def add_clip(*, timeline_id: str, project_id: str, kind: str,
             asset_id: str = "", scene_id: str = "", start_s: float = 0,
             duration_s: float = 0, in_s: float = 0,
             out_s: Optional[float] = None, volume: float = 1.0,
             transition_in: str = "cut", transition_in_s: float = 0,
             text: str = "", settings: Optional[dict] = None) -> str:
    track = _track(timeline_id, kind)
    if not track:
        raise ValueError(f"timeline has no '{kind}' track")

    clip_id = db.new_id("clp")
    db.insert("timeline_clip", {
        "id": clip_id, "track_id": track["id"], "timeline_id": timeline_id,
        "project_id": project_id, "asset_id": asset_id or None,
        "scene_id": scene_id or None, "idx": 0,
        "start_s": round(start_s, 3), "duration_s": round(duration_s, 3),
        "in_s": in_s, "out_s": out_s, "volume": volume,
        "transition_in": transition_in, "transition_in_s": transition_in_s,
        "text": text, "settings": db._dumps(settings or {}),
        "created_at": db.now(),
    })
    return clip_id


def clear_track(timeline_id: str, kind: str) -> int:
    track = _track(timeline_id, kind)
    if not track:
        return 0
    return db.execute("DELETE FROM timeline_clip WHERE track_id=?", (track["id"],))


def move_clip(clip_id: str, start_s: float) -> bool:
    return db.update("timeline_clip", clip_id, {"start_s": round(max(0, start_s), 3)})


def trim_clip(clip_id: str, *, duration_s: Optional[float] = None,
              in_s: Optional[float] = None, out_s: Optional[float] = None) -> bool:
    patch = {}
    if duration_s is not None:
        patch["duration_s"] = round(max(0.1, duration_s), 3)
    if in_s is not None:
        patch["in_s"] = round(max(0, in_s), 3)
    if out_s is not None:
        patch["out_s"] = round(out_s, 3)
    return db.update("timeline_clip", clip_id, patch) if patch else False


def split_clip(clip_id: str, at_s: float) -> Optional[str]:
    """Split one clip into two at an absolute timeline position."""
    clip = db.fetch_one("SELECT * FROM timeline_clip WHERE id=?", (clip_id,),
                        json_fields=("settings",))
    if not clip:
        return None

    offset = at_s - clip["start_s"]
    if offset <= 0.1 or offset >= clip["duration_s"] - 0.1:
        return None  # a split at the very edge would create a zero-length clip

    db.update("timeline_clip", clip_id, {"duration_s": round(offset, 3)})
    return add_clip(
        timeline_id=clip["timeline_id"], project_id=clip["project_id"],
        kind=db.fetch_one("SELECT kind FROM timeline_track WHERE id=?",
                          (clip["track_id"],))["kind"],
        asset_id=clip["asset_id"] or "", scene_id=clip["scene_id"] or "",
        start_s=at_s, duration_s=round(clip["duration_s"] - offset, 3),
        in_s=clip["in_s"] + offset, volume=clip["volume"], text=clip["text"],
        settings=clip["settings"],
    )


def delete_clip(clip_id: str) -> bool:
    return db.execute("DELETE FROM timeline_clip WHERE id=?", (clip_id,)) > 0


def set_track(track_id: str, *, muted: Optional[bool] = None,
              volume: Optional[float] = None) -> bool:
    patch = {}
    if muted is not None:
        patch["muted"] = 1 if muted else 0
    if volume is not None:
        patch["volume"] = max(0.0, min(2.0, float(volume)))
    return db.update("timeline_track", track_id, patch) if patch else False


def ripple_from(timeline_id: str, kind: str, from_start_s: float,
                delta_s: float) -> int:
    """Shift every later clip on a track — how a duration change propagates."""
    track = _track(timeline_id, kind)
    if not track or abs(delta_s) < 0.001:
        return 0
    return db.execute(
        "UPDATE timeline_clip SET start_s = start_s + ? "
        "WHERE track_id=? AND start_s >= ?",
        (delta_s, track["id"], from_start_s))


# =============================================================================
# VOICE TIMING ENGINE
# =============================================================================

def analyse_timing(project_id: str) -> dict:
    """Compare planned scene durations against measured narration durations.

    Reports; never silently corrects. Scenes with no generated voiceover are
    reported as `unknown` rather than assumed to fit — we have not measured
    them, so we do not have an opinion yet.
    """
    scenes = db.fetch_all(
        """SELECT s.* FROM scene s JOIN storyboard b ON b.id = s.storyboard_id
           WHERE s.project_id=? AND b.is_current=1 ORDER BY s.idx""",
        (project_id,))
    if not scenes:
        return {"conflicts": [], "unknown": [], "ok": [],
                "note": "no storyboard to analyse"}

    voiceovers = {
        v["scene_id"]: v for v in db.fetch_all(
            "SELECT scene_id, duration_s, status, text FROM voiceover "
            "WHERE project_id=? AND scene_id IS NOT NULL", (project_id,))
    }

    conflicts, unknown, ok = [], [], []

    for scene in scenes:
        planned = float(scene["duration_s"])
        voiceover = voiceovers.get(scene["id"])

        if not voiceover or voiceover["duration_s"] is None:
            reason = ("no voiceover generated yet" if not voiceover
                      else "voiceover audio duration could not be measured")
            unknown.append({
                "scene_id": scene["id"], "scene_idx": scene["idx"],
                "planned_s": planned, "narration_s": None, "reason": reason,
            })
            continue

        actual = float(voiceover["duration_s"])
        delta = actual - planned

        if abs(delta) <= TIMING_TOLERANCE_S:
            ok.append({"scene_id": scene["id"], "scene_idx": scene["idx"],
                       "planned_s": planned, "narration_s": round(actual, 2)})
            continue

        conflicts.append({
            "scene_id": scene["id"],
            "scene_idx": scene["idx"],
            "planned_s": planned,
            "narration_s": round(actual, 2),
            "delta_s": round(delta, 2),
            "kind": "narration_longer" if delta > 0 else "narration_shorter",
            "message": (
                f"Scene {scene['idx'] + 1} is planned at {planned:.1f}s but the "
                f"narration runs {actual:.1f}s "
                f"({abs(delta):.1f}s {'over' if delta > 0 else 'under'})."
            ),
            "options": _timing_options(delta, actual, planned),
        })

    return {
        "conflicts": conflicts,
        "unknown": unknown,
        "ok": ok,
        "total_planned_s": round(sum(s["duration_s"] for s in scenes), 2),
        "total_narration_s": round(
            sum(v["duration_s"] for v in voiceovers.values()
                if v["duration_s"] is not None), 2),
        "note": ("Timing differences are reported, never applied automatically. "
                 "Choose a resolution per scene."),
    }


def _timing_options(delta: float, actual: float, planned: float) -> list[dict]:
    """The four resolutions from the spec, with their real trade-offs."""
    options = [{
        "action": "extend_visual",
        "label": f"Extend the visual to {actual:.1f}s",
        "effect": "The shot holds longer. Nothing is cut and the voice is "
                  "untouched; later scenes shift.",
        "recommended": delta > 0,
    }, {
        "action": "shorten_narration",
        "label": "Rewrite the narration shorter",
        "effect": f"Ask the Writer to cut roughly "
                  f"{max(1, int(abs(delta) * 2.5))} words, then regenerate the voice.",
        "recommended": False,
    }, {
        "action": "speed_up_voice",
        "label": f"Speed the voice to {min(1.35, actual / max(planned, 0.1)):.2f}×",
        "effect": "Keeps the planned length, but audibly changes delivery. "
                  "Above about 1.2× it starts to sound rushed.",
        "recommended": False,
        "warning": (actual / max(planned, 0.1)) > 1.2,
    }, {
        "action": "manual",
        "label": "Adjust the scene by hand",
        "effect": "Set the duration yourself in the timeline editor.",
        "recommended": False,
    }]
    if delta < 0:
        options[0]["label"] = f"Shorten the visual to {actual:.1f}s"
        options[0]["effect"] = ("Removes the silent tail after the narration ends. "
                                "Later scenes shift earlier.")
    return options


def apply_timing_resolution(project_id: str, scene_id: str, action: str, *,
                            value: Optional[float] = None) -> dict:
    """Act on an explicitly chosen resolution.

    Only the two mechanical resolutions are applied here. `shorten_narration`
    needs the Writer and a fresh voice generation, so it returns a directive
    for the caller rather than pretending to have done it.
    """
    scene = db.fetch_one("SELECT * FROM scene WHERE id=? AND project_id=?",
                         (scene_id, project_id))
    if not scene:
        return {"ok": False, "error": "scene not found"}

    voiceover = db.fetch_one(
        "SELECT duration_s FROM voiceover WHERE scene_id=? AND project_id=?",
        (scene_id, project_id))
    narration_s = (voiceover or {}).get("duration_s")

    if action == "extend_visual":
        target = value if value is not None else narration_s
        if target is None:
            return {"ok": False,
                    "error": "no measured narration duration to extend to"}
        delta = float(target) - float(scene["duration_s"])
        db.update("scene", scene_id, {"duration_s": round(float(target), 2)})
        _reflow_scenes(project_id)
        return {"ok": True, "applied": "extend_visual",
                "new_duration_s": round(float(target), 2),
                "shifted_later_scenes_by_s": round(delta, 2)}

    if action == "speed_up_voice":
        if not narration_s or not scene["duration_s"]:
            return {"ok": False, "error": "cannot compute a speed factor without "
                                          "a measured narration duration"}
        factor = round(float(narration_s) / float(scene["duration_s"]), 3)
        if factor > 1.5:
            return {"ok": False,
                    "error": f"a {factor:.2f}× speed-up would be unintelligible; "
                             f"extend the visual or shorten the narration instead"}
        return {"ok": True, "applied": "speed_up_voice", "speed_factor": factor,
                "requires": "voice_regeneration",
                "note": f"Regenerate this scene's voiceover at {factor:.2f}× to apply."}

    if action == "shorten_narration":
        return {"ok": True, "applied": "shorten_narration",
                "requires": "script_rewrite_and_voice_regeneration",
                "target_words": max(1, int(float(scene["duration_s"]) * 2.5)),
                "note": "Rewrite this scene's narration to the target length, "
                        "then regenerate its voiceover."}

    if action == "manual":
        if value is None:
            return {"ok": False, "error": "manual adjustment needs a duration"}
        db.update("scene", scene_id, {"duration_s": round(float(value), 2)})
        _reflow_scenes(project_id)
        return {"ok": True, "applied": "manual",
                "new_duration_s": round(float(value), 2)}

    return {"ok": False, "error": f"unknown timing action '{action}'"}


def _reflow_scenes(project_id: str) -> None:
    """Recompute scene start times after a duration change."""
    scenes = db.fetch_all(
        """SELECT s.id, s.duration_s FROM scene s
           JOIN storyboard b ON b.id = s.storyboard_id
           WHERE s.project_id=? AND b.is_current=1 ORDER BY s.idx""",
        (project_id,))
    cursor = 0.0
    for scene in scenes:
        db.update("scene", scene["id"], {"start_s": round(cursor, 2)})
        cursor += float(scene["duration_s"])


# =============================================================================
# AUTO ASSEMBLY
# =============================================================================

def auto_assemble(project_id: str, *, brief: dict,
                  resolution: str = "1080p", fps: int = 30) -> dict:
    """Build an editable draft timeline from the project's real assets.

    Every clip points at an asset that exists. Scenes without a generated
    asset are reported in `skipped` and left as a gap — an honest hole the
    user can see and fill, rather than a silent substitution.

    The result is a draft: nothing here is irreversible, and the user can
    move, trim, split, or replace anything afterwards.
    """
    timeline = get_or_create(
        project_id, aspect_ratio=brief.get("aspect_ratio", "16:9"),
        fps=fps, resolution=resolution)
    timeline_id = timeline["id"]

    for kind in TRACK_KINDS:
        clear_track(timeline_id, kind)

    scenes = db.fetch_all(
        """SELECT s.* FROM scene s JOIN storyboard b ON b.id = s.storyboard_id
           WHERE s.project_id=? AND b.is_current=1 ORDER BY s.idx""",
        (project_id,))

    voiceovers = {
        v["scene_id"]: v for v in db.fetch_all(
            "SELECT * FROM voiceover WHERE project_id=? AND scene_id IS NOT NULL "
            "AND asset_id IS NOT NULL", (project_id,))
    }

    placed, skipped, cursor = 0, [], 0.0

    for scene in scenes:
        voiceover = voiceovers.get(scene["id"])
        # Real narration length wins over the plan — the timeline must match
        # the audio that actually exists.
        duration = float(scene["duration_s"])
        if voiceover and voiceover.get("duration_s"):
            duration = float(voiceover["duration_s"])

        if not scene["selected_asset_id"]:
            skipped.append({
                "scene_idx": scene["idx"], "scene_id": scene["id"],
                "reason": f"no generated asset (scene status: {scene['status']})",
                "gap_start_s": round(cursor, 3), "gap_duration_s": round(duration, 3),
            })
            cursor += duration
            continue

        add_clip(
            timeline_id=timeline_id, project_id=project_id, kind="video",
            asset_id=scene["selected_asset_id"], scene_id=scene["id"],
            start_s=cursor, duration_s=duration,
            transition_in=scene["transition"],
            transition_in_s=scene["transition_duration"] if scene["transition"] != "cut" else 0,
        )
        placed += 1

        if voiceover and voiceover.get("asset_id"):
            add_clip(
                timeline_id=timeline_id, project_id=project_id, kind="voice",
                asset_id=voiceover["asset_id"], scene_id=scene["id"],
                start_s=cursor,
                duration_s=float(voiceover.get("duration_s") or duration),
                volume=1.0,
            )
        cursor += duration

    total = round(cursor, 3)
    music_clips = _place_music(project_id, timeline_id, total)
    caption_clips = _place_captions(project_id, timeline_id)

    db.update("timeline", timeline_id, {"duration_s": total})

    return {
        "timeline_id": timeline_id,
        "duration_s": total,
        "scenes_placed": placed,
        "scenes_skipped": len(skipped),
        "skipped": skipped,
        "music_clips": music_clips,
        "caption_clips": caption_clips,
        "is_draft": True,
        "note": ("This is an editable draft. Nothing is rendered yet and every "
                 "clip can still be moved, trimmed, or replaced."),
    }


def _place_music(project_id: str, timeline_id: str, total_duration: float) -> int:
    """Lay music under the video, looping to fill.

    Only tracks with an actual asset are placed, and rights status is carried
    onto the clip so the renderer and QC can see it.
    """
    tracks = db.fetch_all(
        "SELECT * FROM music_track WHERE project_id=? AND asset_id IS NOT NULL "
        "ORDER BY start_s", (project_id,))
    if not tracks or total_duration <= 0:
        return 0

    placed = 0
    for track in tracks:
        asset = db.fetch_one("SELECT duration_s FROM media_asset WHERE id=?",
                             (track["asset_id"],))
        clip_len = (asset or {}).get("duration_s") or track["duration_s"] or total_duration
        cursor = float(track["start_s"] or 0)

        # Loop until the video ends, capped so a corrupt duration cannot spin.
        for _ in range(200):
            if cursor >= total_duration:
                break
            remaining = total_duration - cursor
            add_clip(
                timeline_id=timeline_id, project_id=project_id, kind="music",
                asset_id=track["asset_id"], start_s=cursor,
                duration_s=round(min(clip_len, remaining), 3),
                volume=track["volume"],
                settings={
                    "fade_in_s": track["fade_in_s"],
                    "fade_out_s": track["fade_out_s"],
                    "ducking": bool(track["ducking"]),
                    "duck_to": track["duck_to"],
                    "rights_status": track["rights_status"],
                },
            )
            placed += 1
            cursor += clip_len
    return placed


def _place_captions(project_id: str, timeline_id: str) -> int:
    track = db.fetch_one(
        "SELECT * FROM caption_track WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
        (project_id,), json_fields=("cues", "style_config"))
    if not track or not track.get("cues"):
        return 0

    placed = 0
    for cue in track["cues"]:
        add_clip(
            timeline_id=timeline_id, project_id=project_id, kind="caption",
            start_s=cue["start_s"],
            duration_s=round(cue["end_s"] - cue["start_s"], 3),
            text=cue["text"],
            settings={"style": track["style"], **(track.get("style_config") or {})},
        )
        placed += 1
    return placed


def to_render_json(project_id: str) -> dict:
    """Serialise the timeline for the renderer.

    Deliberately a flat, self-contained document: the render worker resolves
    it without further DB access, so a timeline edited mid-render cannot
    change what is being produced.
    """
    timeline = load(project_id)
    if not timeline:
        return {}

    from .storage import get_storage
    storage = get_storage()

    doc = {
        "version": 1,
        "project_id": project_id,
        "fps": timeline["fps"],
        "width": timeline["width"],
        "height": timeline["height"],
        "aspect_ratio": timeline["aspect_ratio"],
        "duration_s": timeline["duration_s"],
        "tracks": [],
    }

    for track in timeline["tracks"]:
        clips = []
        for clip in track["clips"]:
            asset = clip.get("asset")
            clips.append({
                "id": clip["id"],
                "asset_id": clip["asset_id"],
                "path": storage.local_path(asset["storage_key"]) if asset else None,
                "storage_key": asset["storage_key"] if asset else "",
                "mime": asset["mime"] if asset else "",
                "asset_kind": asset["kind"] if asset else "",
                "start_s": clip["start_s"],
                "duration_s": clip["duration_s"],
                "in_s": clip["in_s"],
                "volume": clip["volume"],
                "transition_in": clip["transition_in"],
                "transition_in_s": clip["transition_in_s"],
                "text": clip["text"],
                "settings": clip["settings"] or {},
                "missing_asset": clip["missing_asset"],
            })
        doc["tracks"].append({
            "kind": track["kind"], "muted": bool(track["muted"]),
            "volume": track["volume"], "clips": clips,
        })
    return doc
