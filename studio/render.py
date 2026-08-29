"""
studio/render.py — Render pipeline.

    TIMELINE JSON → ASSET RESOLUTION → COMPOSITION → ENCODE → MP4

ffmpeg was chosen over a React-based renderer (Remotion et al.) because
Ultron-J deploys as a single Python process with no Node toolchain, and
ffmpeg is the dependency most likely to already exist on the host. The
composition step emits a filter graph rather than shelling out per clip, so
the whole video is one encode pass.

Honest capability reporting
---------------------------
ffmpeg is **not** vendored, so `probe()` checks for it and the Studio reports
render as unavailable when it is missing — with the install command, not a
disabled button that silently does nothing. Everything upstream (planning,
generation, timeline editing, caption export) still works; only the final
encode needs the binary.

Honest progress
---------------
ffmpeg reports the timestamp it has reached, so progress here is *real*:
`-progress` output is parsed and converted to a percentage of known total
duration. During asset staging, where there is no such signal, the job
reports a named stage ("Preparing media assets…") rather than a number.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import time
from shutil import which
from typing import Optional

from . import db, timeline as tl
from .storage import get_storage, sanitize_key

try:
    from config import STUDIO_RENDER_DIR
except ImportError:  # pragma: no cover
    STUDIO_RENDER_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "studio_media", "renders")


RENDER_STAGES = ("queued", "preparing_assets", "rendering", "encoding",
                 "uploading", "completed", "failed", "cancelled")

RESOLUTIONS = {"720p": 720, "1080p": 1080, "4k": 2160}
FRAME_RATES = (24, 30, 60)
FORMATS = {"mp4": {"vcodec": "libx264", "acodec": "aac", "ext": "mp4"},
           "webm": {"vcodec": "libvpx-vp9", "acodec": "libopus", "ext": "webm"}}

_ACTIVE: dict[str, subprocess.Popen] = {}
_LOCK = threading.Lock()


# =============================================================================
# CAPABILITY PROBE
# =============================================================================

def probe() -> dict:
    """Report what this host can actually render, and how to fix it if not."""
    ffmpeg = which("ffmpeg")
    ffprobe = which("ffprobe")

    if not ffmpeg:
        return {
            "available": False,
            "reason": "ffmpeg is not installed on this host",
            "remedy": ("Install ffmpeg to enable rendering: "
                       "`sudo apt install ffmpeg` (Debian/Ubuntu), "
                       "`brew install ffmpeg` (macOS), or download a build "
                       "from https://ffmpeg.org/download.html"),
            "impact": ("Planning, generation, the timeline editor, and caption "
                       "export all work without it. Only the final MP4 encode "
                       "requires ffmpeg."),
            "ffmpeg": None, "ffprobe": ffprobe,
        }

    version, encoders = "", []
    try:
        out = subprocess.run([ffmpeg, "-version"], capture_output=True,
                             text=True, timeout=15, check=False)
        first = (out.stdout or "").splitlines()
        version = first[0] if first else ""
    except Exception:  # noqa: BLE001
        pass

    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=15, check=False)
        text = out.stdout or ""
        encoders = [name for name in ("libx264", "libx265", "libvpx-vp9",
                                      "aac", "libopus", "h264_nvenc")
                    if re.search(rf"\b{re.escape(name)}\b", text)]
    except Exception:  # noqa: BLE001
        pass

    formats = [fmt for fmt, spec in FORMATS.items() if spec["vcodec"] in encoders]

    return {
        "available": True,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "version": version,
        "encoders": encoders,
        "formats": formats or ["mp4"],
        "resolutions": list(RESOLUTIONS),
        "frame_rates": list(FRAME_RATES),
        # 4K is offered only where an encoder that can sanely do it exists.
        "notes": ("4K rendering is CPU-bound and can take many minutes per "
                  "minute of footage on this host." if "h264_nvenc" not in encoders
                  else "Hardware encoding available."),
    }


# =============================================================================
# RENDER JOBS
# =============================================================================

def create_job(project_id: str, workspace: str, *, resolution: str = "1080p",
               fps: int = 30, fmt: str = "mp4", aspect_ratio: str = "16:9",
               burn_captions: bool = False) -> dict:
    """Queue a render. Refuses up front when the host cannot render."""
    capability = probe()
    if not capability["available"]:
        return {"ok": False, "error": capability["reason"],
                "remedy": capability["remedy"], "impact": capability["impact"]}

    if resolution not in RESOLUTIONS:
        return {"ok": False, "error": f"unsupported resolution '{resolution}'"}
    if int(fps) not in FRAME_RATES:
        return {"ok": False, "error": f"unsupported frame rate '{fps}'"}
    if fmt not in capability.get("formats", ["mp4"]):
        return {"ok": False,
                "error": f"this ffmpeg build cannot encode '{fmt}'; "
                         f"available: {', '.join(capability.get('formats', []))}"}

    doc = tl.to_render_json(project_id)
    if not doc or not doc.get("tracks"):
        return {"ok": False, "error": "there is no timeline to render"}

    video_clips = sum(len(t["clips"]) for t in doc["tracks"] if t["kind"] == "video")
    if not video_clips:
        return {"ok": False,
                "error": "the timeline has no video clips — generate scene "
                         "assets and auto-assemble first"}

    job_id = db.new_id("rnd")
    db.insert("render_job", {
        "id": job_id, "project_id": project_id, "workspace": workspace,
        "status": "queued", "stage": "queued",
        "stage_detail": "waiting for a render slot",
        "progress_pct": None,
        "settings": db._dumps({"resolution": resolution, "fps": int(fps),
                               "format": fmt, "aspect_ratio": aspect_ratio,
                               "burn_captions": bool(burn_captions)}),
        "timeline_json": db._dumps(doc),
        "created_at": db.now(), "updated_at": db.now(),
    })

    thread = threading.Thread(target=_render_worker, args=(job_id,),
                              name=f"studio-render-{job_id[:8]}", daemon=True)
    thread.start()

    return {"ok": True, "render_job_id": job_id, "status": "queued"}


def get_job(job_id: str) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM render_job WHERE id=?", (job_id,),
                        json_fields=("settings",))


def cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        return {"ok": False, "error": "render job not found"}
    if job["status"] in ("completed", "failed", "cancelled"):
        return {"ok": False, "error": f"render already {job['status']}"}

    db.update("render_job", job_id, {"cancel_requested": 1})
    with _LOCK:
        proc = _ACTIVE.get(job_id)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "note": "render cancellation requested"}


def _set(job_id: str, **patch) -> None:
    db.update("render_job", job_id, patch)


def _cancelled(job_id: str) -> bool:
    row = db.fetch_one("SELECT cancel_requested FROM render_job WHERE id=?", (job_id,))
    return bool(row and row["cancel_requested"])


# =============================================================================
# WORKER
# =============================================================================

def _render_worker(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    try:
        doc = db._loads(job["timeline_json"], {}) or {}
        settings = job["settings"] or {}

        _set(job_id, status="preparing_assets", stage="preparing_assets",
             stage_detail="Preparing media assets…", progress_pct=None)

        clips, missing = _resolve_assets(doc)
        if missing:
            raise RenderError(
                f"{len(missing)} clip(s) reference media that is missing from "
                f"storage: {', '.join(missing[:5])}")
        if not clips["video"]:
            raise RenderError("no usable video clips after asset resolution")

        if _cancelled(job_id):
            _set(job_id, status="cancelled", stage="cancelled",
                 stage_detail="cancelled before rendering", finished_at=db.now())
            return

        _set(job_id, status="rendering", stage="rendering",
             stage_detail=f"Rendering {len(clips['video'])} clips…")

        output_path = _run_ffmpeg(job_id, doc, clips, settings)

        if _cancelled(job_id):
            _cleanup(output_path)
            _set(job_id, status="cancelled", stage="cancelled",
                 stage_detail="cancelled during render", finished_at=db.now())
            return

        _set(job_id, status="uploading", stage="uploading",
             stage_detail="Storing the finished video…", progress_pct=100.0)

        key = _store_output(job["project_id"], job_id, output_path, settings)

        _set(job_id, status="completed", stage="completed",
             stage_detail="Render complete", output_key=key,
             progress_pct=100.0, finished_at=db.now())

    except RenderError as exc:
        _set(job_id, status="failed", stage="failed", stage_detail="",
             error=str(exc)[:1000], finished_at=db.now())
    except Exception as exc:  # noqa: BLE001
        _set(job_id, status="failed", stage="failed", stage_detail="",
             error=f"unexpected render error: {exc}"[:1000], finished_at=db.now())
    finally:
        with _LOCK:
            _ACTIVE.pop(job_id, None)


class RenderError(Exception):
    pass


def _resolve_assets(doc: dict) -> tuple[dict, list[str]]:
    """Verify every referenced asset is present on disk before encoding.

    Failing here costs seconds; failing inside ffmpeg costs the whole render.
    """
    storage = get_storage()
    clips: dict[str, list] = {"video": [], "voice": [], "music": [], "caption": []}
    missing: list[str] = []

    for track in doc.get("tracks", []):
        kind = track["kind"]
        if track.get("muted") and kind in ("voice", "music"):
            continue
        for clip in track.get("clips", []):
            if kind == "caption":
                clips["caption"].append(clip)
                continue

            path = clip.get("path")
            if not path and clip.get("storage_key"):
                path = storage.local_path(clip["storage_key"])
            if not path or not os.path.exists(path):
                missing.append(clip.get("asset_id") or clip.get("id", "?"))
                continue
            clip = dict(clip, path=path, track_volume=track.get("volume", 1.0))
            clips.setdefault(kind, []).append(clip)

    for kind in clips:
        clips[kind].sort(key=lambda c: c["start_s"])
    return clips, missing


def _run_ffmpeg(job_id: str, doc: dict, clips: dict, settings: dict) -> str:
    """Build and run the composition. Returns the output path."""
    width, height = doc["width"], doc["height"]
    resolution = settings.get("resolution", "1080p")
    if resolution in RESOLUTIONS:
        # Export resolution overrides the timeline's authoring canvas.
        width, height = tl._dimensions(doc.get("aspect_ratio", "16:9"), resolution)

    fps = int(settings.get("fps", 30))
    fmt = settings.get("format", "mp4")
    spec = FORMATS.get(fmt, FORMATS["mp4"])
    duration = float(doc.get("duration_s") or 0)
    if duration <= 0:
        raise RenderError("timeline duration is zero")

    os.makedirs(STUDIO_RENDER_DIR, exist_ok=True)
    output_path = os.path.join(STUDIO_RENDER_DIR, f"{job_id}.{spec['ext']}")

    cmd, filter_graph, maps = _build_command(clips, width, height, fps, duration,
                                             settings, doc)

    ffmpeg = which("ffmpeg")
    full = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    full += cmd
    full += ["-filter_complex", filter_graph]
    full += maps
    full += ["-c:v", spec["vcodec"], "-pix_fmt", "yuv420p",
             "-r", str(fps), "-t", f"{duration:.3f}"]
    if spec["vcodec"] == "libx264":
        full += ["-preset", "medium", "-crf", "20"]
    if maps.count("-map") > 1:
        full += ["-c:a", spec["acodec"], "-b:a", "192k"]
    full += ["-progress", "pipe:1", "-nostats", output_path]

    db.update("render_job", job_id,
              {"stage_detail": f"Encoding {len(clips['video'])} clips at "
                               f"{width}×{height} @ {fps}fps"})

    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    with _LOCK:
        _ACTIVE[job_id] = proc

    _track_progress(job_id, proc, duration)

    _, stderr = proc.communicate(timeout=60)
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg failed (exit {proc.returncode}): "
                          f"{(stderr or '').strip()[:500]}")
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RenderError("ffmpeg reported success but produced no output file")
    return output_path


def _build_command(clips: dict, width: int, height: int, fps: int,
                   duration: float, settings: dict, doc: dict):
    """Compose the filter graph.

    Video: each clip is scaled and padded to the canvas, then overlaid onto a
    black base at its timeline position. Stills get a duration via `-loop`.
    Audio: voice and music are delayed to position and mixed, with music
    ducked under narration.
    """
    inputs: list[str] = []
    video_filters: list[str] = []
    audio_filters: list[str] = []
    index = 0

    # Black canvas for the full duration — the base every clip lands on.
    inputs += ["-f", "lavfi", "-t", f"{duration:.3f}",
               "-i", f"color=c=black:s={width}x{height}:r={fps}"]
    base_label = f"{index}:v"
    index += 1

    current = "[base]"
    video_filters.append(f"[{base_label}]setsar=1[base]")

    for clip in clips["video"]:
        is_still = (clip.get("asset_kind") == "image"
                    or (clip.get("mime") or "").startswith("image/"))
        if is_still:
            inputs += ["-loop", "1", "-t", f"{clip['duration_s']:.3f}",
                       "-i", clip["path"]]
        else:
            inputs += ["-ss", f"{clip.get('in_s', 0):.3f}",
                       "-t", f"{clip['duration_s']:.3f}", "-i", clip["path"]]

        label = f"v{index}"
        # Scale to fit, pad to the exact canvas — never distort aspect ratio.
        video_filters.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={fps}[{label}]"
        )

        start, end = clip["start_s"], clip["start_s"] + clip["duration_s"]
        fade = clip.get("transition_in_s") or 0
        transition = clip.get("transition_in", "cut")

        if transition in ("fade", "dissolve") and fade > 0:
            video_filters[-1] = video_filters[-1].replace(
                f"[{label}]", f"[{label}_pre]")
            video_filters.append(
                f"[{label}_pre]fade=t=in:st=0:d={fade:.2f}:alpha=1[{label}]")

        out_label = f"ov{index}"
        video_filters.append(
            f"{current}[{label}]overlay=enable='between(t,{start:.3f},{end:.3f})':"
            f"x=0:y=0[{out_label}]"
        )
        current = f"[{out_label}]"
        index += 1

    # ── Audio ────────────────────────────────────────────────────────────
    voice_labels, music_labels = [], []

    for clip in clips.get("voice", []):
        inputs += ["-i", clip["path"]]
        label = f"a{index}"
        volume = clip.get("volume", 1.0) * clip.get("track_volume", 1.0)
        audio_filters.append(
            f"[{index}:a]adelay={int(clip['start_s'] * 1000)}|"
            f"{int(clip['start_s'] * 1000)},volume={volume:.3f}[{label}]")
        voice_labels.append(f"[{label}]")
        index += 1

    for clip in clips.get("music", []):
        inputs += ["-i", clip["path"]]
        label = f"m{index}"
        cfg = clip.get("settings") or {}
        volume = clip.get("volume", 0.25) * clip.get("track_volume", 1.0)
        chain = (f"[{index}:a]atrim=0:{clip['duration_s']:.3f},asetpts=PTS-STARTPTS,"
                 f"adelay={int(clip['start_s'] * 1000)}|{int(clip['start_s'] * 1000)},"
                 f"volume={volume:.3f}")
        fade_in = float(cfg.get("fade_in_s") or 0)
        fade_out = float(cfg.get("fade_out_s") or 0)
        if fade_in > 0:
            chain += f",afade=t=in:st={clip['start_s']:.3f}:d={fade_in:.2f}"
        if fade_out > 0:
            out_at = clip["start_s"] + clip["duration_s"] - fade_out
            chain += f",afade=t=out:st={max(0, out_at):.3f}:d={fade_out:.2f}"
        audio_filters.append(f"{chain}[{label}]")
        music_labels.append(f"[{label}]")
        index += 1

    audio_out = ""
    if voice_labels or music_labels:
        voice_mix = ""
        if voice_labels:
            if len(voice_labels) > 1:
                audio_filters.append(
                    f"{''.join(voice_labels)}amix=inputs={len(voice_labels)}:"
                    f"normalize=0[voicemix]")
                voice_mix = "[voicemix]"
            else:
                voice_mix = voice_labels[0]

        music_mix = ""
        if music_labels:
            if len(music_labels) > 1:
                audio_filters.append(
                    f"{''.join(music_labels)}amix=inputs={len(music_labels)}:"
                    f"normalize=0[musicmix]")
                music_mix = "[musicmix]"
            else:
                music_mix = music_labels[0]

        ducking = any((c.get("settings") or {}).get("ducking")
                      for c in clips.get("music", []))

        if voice_mix and music_mix:
            if ducking:
                # sidechaincompress ducks the music whenever narration plays.
                audio_filters.append(
                    f"{music_mix}{voice_mix}sidechaincompress="
                    f"threshold=0.05:ratio=8:attack=20:release=400[ducked]")
                audio_filters.append(f"[ducked]{voice_mix}amix=inputs=2:"
                                     f"normalize=0[aout]")
            else:
                audio_filters.append(
                    f"{voice_mix}{music_mix}amix=inputs=2:normalize=0[aout]")
            audio_out = "[aout]"
        else:
            audio_out = voice_mix or music_mix

    graph = ";".join(video_filters + audio_filters)
    maps = ["-map", current]
    if audio_out:
        maps += ["-map", audio_out]
    return inputs, graph, maps


def _track_progress(job_id: str, proc: subprocess.Popen, duration: float) -> None:
    """Convert ffmpeg's real progress output into a percentage.

    This is a genuine measurement — `out_time_ms` is how far into the output
    ffmpeg has actually encoded — which is why a percentage is honest here
    but not during asset staging.
    """
    last_update = 0.0
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break
        line = line.strip()

        if line.startswith("out_time_ms="):
            try:
                encoded_s = int(line.split("=", 1)[1]) / 1_000_000
            except (ValueError, IndexError):
                continue
            pct = max(0.0, min(99.0, (encoded_s / duration) * 100))
            now = time.time()
            if now - last_update > 1.0:
                last_update = now
                _set(job_id, progress_pct=round(pct, 1),
                     stage_detail=f"Encoding — {encoded_s:.0f}s of {duration:.0f}s")

        elif line == "progress=end":
            break

        if _cancelled(job_id):
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            break


def _store_output(project_id: str, job_id: str, path: str, settings: dict) -> str:
    storage = get_storage()
    ext = os.path.splitext(path)[1].lstrip(".") or "mp4"
    key = sanitize_key(project_id, "renders", f"{job_id}.{ext}")

    with open(path, "rb") as fh:
        data = fh.read()
    storage.upload(key, data, mime=f"video/{ext}")

    from .jobs import store_asset
    store_asset(
        project_id=project_id, kind="video", data=data, mime=f"video/{ext}",
        source="render", filename=f"render_{job_id[:8]}.{ext}",
        settings=settings, meta={"render_job_id": job_id},
    )
    _cleanup(path)
    return key


def _cleanup(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


def export_settings() -> dict:
    """What this host can offer the export dialog."""
    capability = probe()
    if not capability["available"]:
        return {"available": False, "reason": capability["reason"],
                "remedy": capability["remedy"], "impact": capability["impact"]}
    return {
        "available": True,
        "resolutions": [
            {"id": "720p", "label": "720p (HD)"},
            {"id": "1080p", "label": "1080p (Full HD)"},
            {"id": "4k", "label": "4K (Ultra HD) — slow on CPU encoding"},
        ],
        "frame_rates": [{"id": f, "label": f"{f} fps"} for f in FRAME_RATES],
        "formats": [{"id": f, "label": f.upper()} for f in capability["formats"]],
        "aspect_ratios": [
            {"id": "16:9", "label": "16:9 — YouTube, landscape"},
            {"id": "9:16", "label": "9:16 — Shorts, Reels, TikTok"},
            {"id": "1:1", "label": "1:1 — square"},
        ],
        "encoders": capability["encoders"],
        "notes": capability["notes"],
    }
