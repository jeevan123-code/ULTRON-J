"""
studio/handlers.py — Job handlers, registered with the worker pool.

`jobs.py` deliberately knows nothing about agents, voice, or captions — it
only knows how to run a callable safely (retry, cancel, log, isolate). This
module supplies those callables and registers them, which keeps the queue
mechanics independent of the domain and avoids an import cycle.

Each handler receives the job row and returns
`{"asset_id": ..., "actual_cost": ...}`. Raising `ProviderError` with
`retryable=True` asks the worker to retry; anything else fails the job.
"""

from __future__ import annotations

from . import agents, captions, cost, db, jobs
from .providers import registry
from .providers.base import GenerationRequest, JobState, ProviderError
from .providers.voice import measure_duration


# =============================================================================
# IMAGE / VIDEO
# =============================================================================

def _generation_request(job: dict) -> GenerationRequest:
    settings = job.get("settings") or {}
    return GenerationRequest(
        prompt=job["prompt"],
        negative_prompt=settings.get("negative_prompt", ""),
        model=job.get("model") or settings.get("model", ""),
        aspect_ratio=settings.get("aspect_ratio", "16:9"),
        resolution=settings.get("resolution", ""),
        duration_s=float(settings.get("duration_s") or 0),
        variations=int(settings.get("variations") or 1),
        seed=settings.get("seed"),
        image_url=settings.get("image_url", ""),
        extra=settings.get("provider_extra") or {},
    )


def handle_image(job: dict) -> dict:
    return jobs.run_provider_generation(job, kind="image",
                                        request=_generation_request(job))


def handle_video(job: dict) -> dict:
    request = _generation_request(job)
    # Image-to-video only dispatches to a provider that genuinely declares it.
    require = "image_to_video" if request.image_url else "text_to_video"
    return jobs.run_provider_generation(job, kind="video", request=request,
                                        require=require)


# =============================================================================
# VOICE
# =============================================================================

def handle_voice(job: dict) -> dict:
    """Synthesise one narration segment and record its *measured* duration."""
    settings = job.get("settings") or {}
    workspace = job["workspace"]
    text = job["prompt"]

    provider = registry.resolve("voice", workspace,
                                preferred=job.get("provider", ""))
    db.update("generation_job", job["id"], {"provider": provider.name})
    jobs.update_progress(job["id"], stage="synthesising narration",
                         status=JobState.GENERATING)

    voice_id = settings.get("voice_id") or ""
    if not voice_id:
        available = provider.list_voices(settings.get("language", ""))
        if not available:
            raise ProviderError(
                f"{provider.label} returned no usable voices", retryable=False)
        voice_id = available[0].id

    status = provider.generate_speech(
        text, voice_id,
        language=settings.get("language", "en"),
        speed=float(settings.get("speed") or 1.0),
        **(settings.get("provider_extra") or {}),
    )

    if status.state != JobState.COMPLETED or not status.output_bytes:
        raise ProviderError(status.error or "voice generation produced no audio",
                            retryable=False)

    # Measure rather than assume — the timing engine depends on this being real.
    duration = status.duration_s
    if duration is None:
        duration = measure_duration(status.output_bytes, status.mime)

    asset_id = jobs.store_asset(
        project_id=job["project_id"], scene_id=job.get("scene_id") or "",
        kind="voiceover", data=status.output_bytes, mime=status.mime,
        provider=provider.name, model=settings.get("model", ""),
        prompt=text[:500], duration_s=duration,
        settings={"voice_id": voice_id, "speed": settings.get("speed", 1.0)},
        meta={"duration_measured": duration is not None},
    )

    _upsert_voiceover(job, asset_id, voice_id, duration, text, provider.name,
                      settings)

    cost.record_usage(
        workspace=workspace, project_id=job["project_id"], job_id=job["id"],
        provider=provider.name, asset_type="voiceover",
        units=len(text), unit_label="characters",
        estimated_cost=job.get("cost_estimate"), actual_cost=status.actual_cost)

    if duration is None:
        db.log_job(job["id"],
                   "audio generated but its duration could not be measured — "
                   "install ffprobe for accurate timeline synchronisation", "warn")

    return {"asset_id": asset_id, "actual_cost": status.actual_cost}


def _upsert_voiceover(job: dict, asset_id: str, voice_id: str,
                      duration, text: str, provider_name: str,
                      settings: dict) -> None:
    payload = {
        "asset_id": asset_id, "provider": provider_name, "voice_id": voice_id,
        "language": settings.get("language", "en"),
        "speed": float(settings.get("speed") or 1.0),
        "text": text, "duration_s": duration, "status": "completed", "error": "",
    }
    existing = db.fetch_one(
        "SELECT id FROM voiceover WHERE project_id=? AND scene_id IS ?",
        (job["project_id"], job.get("scene_id")))
    if existing:
        db.update("voiceover", existing["id"], payload)
    else:
        payload.update({
            "id": db.new_id("vo"), "project_id": job["project_id"],
            "scene_id": job.get("scene_id"), "segment_id": settings.get("segment_id"),
            "voice_name": settings.get("voice_name", ""),
            "created_at": db.now(), "updated_at": db.now(),
        })
        db.insert("voiceover", payload)


# =============================================================================
# TEXT STAGES
# =============================================================================

def handle_research(job: dict) -> dict:
    settings = job.get("settings") or {}
    agents.research(job["project_id"], job["prompt"],
                    audience=settings.get("audience", ""),
                    use_search=settings.get("use_search", True))
    return {}


def handle_script(job: dict) -> dict:
    settings = job.get("settings") or {}
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (job["project_id"],)) or {}
    script = agents.write_script(
        job["project_id"], brief=brief,
        research_report=agents.get_research(job["project_id"]),
        instruction=settings.get("instruction", ""))
    agents.save_script(job["project_id"], script)
    return {}


def handle_storyboard(job: dict) -> dict:
    brief = db.fetch_one("SELECT * FROM video_brief WHERE project_id=?",
                         (job["project_id"],)) or {}
    script = agents.get_script(job["project_id"])
    if not script:
        raise ProviderError("no script to build a storyboard from", retryable=False)
    board = agents.direct(job["project_id"], brief=brief, script=script)
    agents.save_storyboard(job["project_id"], board, brief=brief,
                           workspace=job["workspace"])
    return {}


def handle_caption(job: dict) -> dict:
    settings = job.get("settings") or {}
    captions.save_track(job["project_id"], style=settings.get("style", "minimal"),
                        language=settings.get("language", "en"))
    return {}


# =============================================================================
# REGISTRATION
# =============================================================================

_REGISTERED = False


def register_all() -> None:
    """Wire handlers into the worker pool. Idempotent."""
    global _REGISTERED
    if _REGISTERED:
        return
    jobs.register_handler("image", handle_image)
    jobs.register_handler("video", handle_video)
    jobs.register_handler("voice", handle_voice)
    jobs.register_handler("research", handle_research)
    jobs.register_handler("script", handle_script)
    jobs.register_handler("storyboard", handle_storyboard)
    jobs.register_handler("caption", handle_caption)
    _REGISTERED = True
