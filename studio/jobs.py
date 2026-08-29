"""
studio/jobs.py — Background job worker for LEBENX STUDIO.

Generation takes minutes and must never run inside a Flask request. Every
expensive operation is enqueued here as a `generation_job` row and executed
by a small pool of daemon threads that poll the database.

Why a DB-backed queue rather than Celery/RQ: Ultron-J ships as a single
process with no broker, and the job table must survive a restart regardless.
Claiming is done with a conditional UPDATE, so two workers cannot take the
same row even though they poll independently. Swapping in a real broker later
means reimplementing `_claim_next()` and nothing else.

Guarantees
----------
* **Retry** — transient failures (`ProviderError.retryable`) retry with
  exponential backoff up to `max_attempts`. Non-retryable failures stop
  immediately; retrying a missing API key wastes time and misleads the user.
* **Cancellation** — cooperative. Setting `cancel_requested` makes the worker
  stop at its next checkpoint and, where the provider supports it, cancel
  remote work too. Where it does not, we say so rather than implying the
  remote job stopped.
* **Idempotency** — a caller-supplied `idempotency_key` is unique-indexed, so
  a double-clicked Generate button returns the existing job.
* **Isolation** — one scene failing marks that scene failed and no more. The
  project and its other scenes continue.
* **Honest progress** — `progress_pct` stays NULL unless a provider reported
  a real number. `stage` carries a truthful name instead.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Callable, Optional

from . import cost, db
from .providers import registry
from .providers.base import (
    GenerationHandle, GenerationRequest, GenerationStatus, JobState,
    NotConnected, ProviderError,
)
from .storage import get_storage, sanitize_key

try:
    from config import STUDIO_JOB_WORKERS
except ImportError:  # pragma: no cover
    STUDIO_JOB_WORKERS = 2


#: How long a provider job may run before we stop polling it.
MAX_JOB_SECONDS = 60 * 30
#: Gap between status polls for async providers.
POLL_INTERVAL_S = 5.0
#: Gap between queue scans when idle.
IDLE_SLEEP_S = 2.0

#: job_type -> handler. Populated by `register_handler`, which lets
#: pipeline.py add research/script/storyboard handlers without jobs.py
#: importing the agent layer (which would be a cycle).
_HANDLERS: dict[str, Callable[[dict], dict]] = {}

_WORKERS: list[threading.Thread] = []
_STOP = threading.Event()
_LOCK = threading.Lock()


def register_handler(job_type: str, handler: Callable[[dict], dict]) -> None:
    _HANDLERS[job_type] = handler


# =============================================================================
# ENQUEUE
# =============================================================================

def enqueue(*, project_id: str, workspace: str, job_type: str,
            prompt: str = "", scene_id: str = "", provider: str = "",
            model: str = "", settings: Optional[dict] = None,
            owner: str = "", idempotency_key: str = "",
            cost_estimate: Optional[float] = None,
            max_attempts: int = 3) -> dict:
    """Create a queued job. Returns the job row.

    An existing job with the same idempotency key is returned untouched — the
    caller gets the original rather than a duplicate charge.
    """
    if idempotency_key:
        existing = db.fetch_one(
            "SELECT * FROM generation_job WHERE idempotency_key=?",
            (idempotency_key,), json_fields=("settings",))
        if existing:
            return existing

    job_id = db.new_id("job")
    now = db.now()
    db.insert("generation_job", {
        "id": job_id,
        "project_id": project_id,
        "workspace": workspace,
        "owner": owner,
        "scene_id": scene_id or None,
        "job_type": job_type,
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "settings": db._dumps(settings or {}),
        "status": JobState.QUEUED.value,
        "stage": "queued",
        "progress_pct": None,
        "cost_estimate": cost_estimate,
        "max_attempts": max_attempts,
        "idempotency_key": idempotency_key or None,
        "created_at": now,
        "updated_at": now,
    })
    db.log_job(job_id, f"queued {job_type}"
                       + (f" for scene {scene_id}" if scene_id else ""))
    return get_job(job_id)


def get_job(job_id: str) -> Optional[dict]:
    return db.fetch_one("SELECT * FROM generation_job WHERE id=?", (job_id,),
                        json_fields=("settings",))


def cancel_job(job_id: str) -> dict:
    """Request cancellation. Cooperative — the worker acts at its next check.

    Returns a note making clear whether remote work was actually stopped,
    because for providers without a cancel API it may still complete and bill.
    """
    job = get_job(job_id)
    if not job:
        return {"ok": False, "error": "job not found"}

    if job["status"] in (JobState.COMPLETED.value, JobState.FAILED.value,
                         JobState.CANCELLED.value):
        return {"ok": False, "error": f"job already {job['status']}"}

    db.update("generation_job", job_id, {"cancel_requested": 1})
    db.log_job(job_id, "cancellation requested", "warn")

    if job["status"] == JobState.QUEUED.value:
        _finish(job_id, JobState.CANCELLED, stage="cancelled before dispatch")
        return {"ok": True, "stopped_remote": True,
                "note": "job cancelled before it reached a provider"}

    return {"ok": True, "stopped_remote": False,
            "note": ("cancellation requested; the worker will stop at its next "
                     "checkpoint. If the provider offers no cancel API the "
                     "remote generation may still complete and bill.")}


def list_jobs(project_id: str, limit: int = 100) -> list[dict]:
    return db.fetch_all(
        "SELECT * FROM generation_job WHERE project_id=? "
        "ORDER BY created_at DESC LIMIT ?",
        (project_id, limit), json_fields=("settings",))


# =============================================================================
# WORKER LOOP
# =============================================================================

def _claim_next() -> Optional[dict]:
    """Atomically take one queued job.

    The `WHERE status='queued'` in the UPDATE is what makes this safe under
    concurrency: only one worker's update matches, the rest see rowcount 0.
    """
    with _LOCK:
        row = db.fetch_one(
            "SELECT * FROM generation_job WHERE status=? AND cancel_requested=0 "
            "ORDER BY created_at LIMIT 1",
            (JobState.QUEUED.value,), json_fields=("settings",))
        if not row:
            return None

        claimed = db.execute(
            "UPDATE generation_job SET status=?, stage=?, started_at=?, "
            "updated_at=?, attempts=attempts+1 WHERE id=? AND status=?",
            (JobState.PREPARING.value, "preparing", db.now(), db.now(),
             row["id"], JobState.QUEUED.value),
        )
        if not claimed:
            return None
    return get_job(row["id"])


def _worker_loop(worker_index: int) -> None:
    while not _STOP.is_set():
        try:
            job = _claim_next()
            if job is None:
                _STOP.wait(IDLE_SLEEP_S)
                continue
            _run_job(job)
        except Exception:  # noqa: BLE001 - a worker must never die
            print(f"[studio.jobs] worker {worker_index} error:\n{traceback.format_exc()}")
            _STOP.wait(IDLE_SLEEP_S)


def _run_job(job: dict) -> None:
    job_id = job["id"]
    handler = _HANDLERS.get(job["job_type"])

    if handler is None:
        _finish(job_id, JobState.FAILED,
                error=f"no handler registered for job type '{job['job_type']}'")
        return

    db.log_job(job_id, f"dispatching {job['job_type']} "
                       f"(attempt {job['attempts']}/{job['max_attempts']})")
    try:
        result = handler(job)
        _finish(job_id, JobState.COMPLETED,
                stage="completed",
                result_asset_id=result.get("asset_id"),
                actual_cost=result.get("actual_cost"))
        db.log_job(job_id, "completed")

    except ProviderError as exc:
        _handle_failure(job, exc.message, retryable=exc.retryable)
    except registry.NoProviderAvailable as exc:
        # Never retryable: no amount of waiting connects a provider.
        _handle_failure(job, exc.message, retryable=False)
    except Exception as exc:  # noqa: BLE001
        db.log_job(job_id, traceback.format_exc()[:1500], "error")
        _handle_failure(job, f"unexpected error: {exc}", retryable=False)


def _handle_failure(job: dict, message: str, *, retryable: bool) -> None:
    """Retry transient faults with backoff; fail fast on everything else."""
    job_id = job["id"]
    attempts = job["attempts"]
    max_attempts = job["max_attempts"]

    if retryable and attempts < max_attempts:
        delay = min(2 ** attempts, 60)
        db.log_job(job_id, f"retryable failure: {message} — retrying in {delay}s "
                           f"(attempt {attempts}/{max_attempts})", "warn")
        db.update("generation_job", job_id, {
            "status": JobState.QUEUED.value,
            "stage": f"retrying in {delay}s",
            "error": message,
        })
        # Back off before this worker looks for more work. Sleeping here (on
        # a worker thread, never a request thread) is enough with a small
        # pool; a broker-backed queue would use a visibility timeout instead.
        _STOP.wait(delay)
        return

    reason = message if not retryable else f"{message} (gave up after {attempts} attempts)"
    db.log_job(job_id, f"failed: {reason}", "error")
    _finish(job_id, JobState.FAILED, error=reason)

    # Scene-level isolation: mark only this scene failed. The project and its
    # other scenes are untouched, so the pipeline can carry on around it.
    if job.get("scene_id"):
        db.update("scene", job["scene_id"],
                  {"status": "failed", "error": reason[:500]})


def _finish(job_id: str, state: JobState, *, stage: str = "",
            error: str = "", result_asset_id: Optional[str] = None,
            actual_cost: Optional[float] = None) -> None:
    patch = {
        "status": state.value,
        "stage": stage or state.value,
        "finished_at": db.now(),
    }
    if error:
        patch["error"] = error[:1000]
    if result_asset_id:
        patch["result_asset_id"] = result_asset_id
    if actual_cost is not None:
        patch["actual_cost"] = actual_cost
    db.update("generation_job", job_id, patch)


def update_progress(job_id: str, *, stage: str = "",
                    progress_pct: Optional[float] = None,
                    status: Optional[JobState] = None) -> None:
    """Record progress.

    `progress_pct` is written only when a provider genuinely reported one;
    callers pass None otherwise and the UI shows `stage` instead. There is no
    code path here that advances a percentage on a timer.
    """
    patch: dict = {}
    if stage:
        patch["stage"] = stage
    if progress_pct is not None:
        patch["progress_pct"] = max(0.0, min(100.0, float(progress_pct)))
    if status is not None:
        patch["status"] = status.value
    if patch:
        db.update("generation_job", job_id, patch)


def is_cancelled(job_id: str) -> bool:
    row = db.fetch_one("SELECT cancel_requested FROM generation_job WHERE id=?",
                       (job_id,))
    return bool(row and row["cancel_requested"])


# =============================================================================
# SHARED PROVIDER-JOB DRIVER
# =============================================================================

def run_provider_generation(job: dict, *, kind: str, request: GenerationRequest,
                            require: str = "") -> dict:
    """Drive one image/video generation to completion and store the asset.

    Shared by the image and video handlers because the flow is identical once
    the provider is resolved: dispatch, poll to a terminal state honouring
    cancellation, download, store, record usage.
    """
    job_id = job["id"]
    workspace = job["workspace"]

    provider = registry.resolve(kind, workspace,
                                preferred=job.get("provider", ""), require=require)
    db.update("generation_job", job_id,
              {"provider": provider.name,
               "model": request.model or job.get("model", "")})
    db.log_job(job_id, f"dispatching to {provider.label}")

    est = cost.estimate(kind, provider, request)
    if est.amount is not None:
        db.update("generation_job", job_id, {"cost_estimate": est.amount})

    update_progress(job_id, stage="submitting to provider",
                    status=JobState.GENERATING)

    if kind == "image":
        handle = provider.generate_image(request)
    elif kind == "video":
        handle = provider.generate_video(request)
    else:
        raise ProviderError(f"unsupported generation kind '{kind}'", retryable=False)

    status = _poll_to_terminal(job_id, provider, handle)

    if status.state == JobState.CANCELLED:
        raise ProviderError("cancelled by user", retryable=False)
    if status.state != JobState.COMPLETED:
        raise ProviderError(status.error or f"provider ended in state "
                                            f"'{status.state.value}'",
                            retryable=False)

    update_progress(job_id, stage="downloading asset", status=JobState.PROCESSING)
    data, mime = _materialise(provider, status)
    if not data:
        raise ProviderError("provider reported success but returned no asset",
                            retryable=False)

    asset_id = store_asset(
        project_id=job["project_id"], scene_id=job.get("scene_id") or "",
        kind=kind, data=data, mime=mime or status.mime,
        provider=provider.name, model=request.model,
        prompt=request.prompt,
        settings={"aspect_ratio": request.aspect_ratio,
                  "resolution": request.resolution,
                  "duration_s": request.duration_s},
        width=status.width, height=status.height,
        duration_s=status.duration_s,
    )

    cost.record_usage(
        workspace=workspace, project_id=job["project_id"], job_id=job_id,
        provider=provider.name, model=request.model, asset_type=kind,
        estimated_cost=est.amount, actual_cost=status.actual_cost,
        unit_label="generation",
    )

    if job.get("scene_id"):
        db.update("scene", job["scene_id"], {
            "status": "completed", "selected_asset_id": asset_id, "error": "",
        })

    return {"asset_id": asset_id, "actual_cost": status.actual_cost}


def _poll_to_terminal(job_id: str, provider, handle: GenerationHandle) -> GenerationStatus:
    """Poll until terminal, cancelled, or timed out."""
    deadline = time.time() + MAX_JOB_SECONDS
    last_stage = ""

    while True:
        if is_cancelled(job_id):
            stopped = False
            try:
                stopped = provider.cancel_generation(handle)
            except Exception:  # noqa: BLE001
                stopped = False
            db.log_job(job_id,
                       "cancelled remotely" if stopped else
                       "cancelled locally — provider offers no cancel API, so "
                       "the remote job may still complete and bill", "warn")
            return GenerationStatus(state=JobState.CANCELLED)

        status = provider.get_generation_status(handle)

        if status.stage and status.stage != last_stage:
            last_stage = status.stage
            db.log_job(job_id, f"provider stage: {status.stage}")
        update_progress(job_id,
                        stage=status.stage or "generating",
                        progress_pct=status.progress_pct)

        if status.terminal:
            return status

        if time.time() > deadline:
            db.log_job(job_id, "timed out waiting for provider", "error")
            return GenerationStatus(
                state=JobState.FAILED,
                error=f"provider did not finish within {MAX_JOB_SECONDS}s")

        _STOP.wait(POLL_INTERVAL_S)


def _materialise(provider, status: GenerationStatus) -> tuple[bytes, str]:
    """Get the actual bytes, whether inline or behind a URL."""
    if status.output_bytes:
        return status.output_bytes, status.mime
    if status.output_urls:
        from .providers import http
        return http.download(status.output_urls[0], provider=provider.name)
    return b"", ""


# =============================================================================
# ASSET STORAGE
# =============================================================================

_EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
    "video/mp4": "mp4", "video/webm": "webm",
    "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav",
    "audio/ogg": "ogg", "text/vtt": "vtt", "application/x-subrip": "srt",
}


def store_asset(*, project_id: str, kind: str, data: bytes, mime: str,
                scene_id: str = "", provider: str = "", model: str = "",
                prompt: str = "", settings: Optional[dict] = None,
                source: str = "generated", filename: str = "",
                width: Optional[int] = None, height: Optional[int] = None,
                duration_s: Optional[float] = None,
                meta: Optional[dict] = None) -> str:
    """Persist bytes through the storage abstraction and index the asset."""
    storage = get_storage()
    asset_id = db.new_id("ast")
    ext = _EXTENSIONS.get((mime or "").split(";")[0].strip(), "bin")
    key = sanitize_key(project_id, kind, f"{asset_id}.{ext}")

    info = storage.upload(key, data, mime=mime)

    db.insert("media_asset", {
        "id": asset_id,
        "project_id": project_id,
        "scene_id": scene_id or None,
        "kind": kind,
        "storage_key": key,
        "filename": filename or f"{asset_id}.{ext}",
        "mime": info.get("mime") or mime,
        "bytes": info.get("bytes", len(data)),
        "duration_s": duration_s,
        "width": width,
        "height": height,
        "source": source,
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "settings": db._dumps(settings or {}),
        "meta": db._dumps(meta or {}),
        "created_at": db.now(),
    })
    return asset_id


# =============================================================================
# LIFECYCLE
# =============================================================================

def start_workers(count: int = 0) -> int:
    """Start the worker pool. Idempotent."""
    global _WORKERS
    count = count or int(STUDIO_JOB_WORKERS or 2)

    with _LOCK:
        _WORKERS = [t for t in _WORKERS if t.is_alive()]
        if _WORKERS:
            return len(_WORKERS)
        _STOP.clear()
        for i in range(max(1, count)):
            thread = threading.Thread(target=_worker_loop, args=(i,),
                                      name=f"studio-job-{i}", daemon=True)
            thread.start()
            _WORKERS.append(thread)
    return len(_WORKERS)


def stop_workers() -> None:
    _STOP.set()


def worker_status() -> dict:
    alive = [t.name for t in _WORKERS if t.is_alive()]
    queued = db.fetch_one(
        "SELECT COUNT(*) AS n FROM generation_job WHERE status=?",
        (JobState.QUEUED.value,))
    running = db.fetch_one(
        "SELECT COUNT(*) AS n FROM generation_job WHERE status IN (?,?,?,?)",
        (JobState.PREPARING.value, JobState.GENERATING.value,
         JobState.PROCESSING.value, "draft"))
    return {
        "workers": len(alive),
        "worker_names": alive,
        "queued": (queued or {}).get("n", 0),
        "in_flight": (running or {}).get("n", 0),
        "handlers": sorted(_HANDLERS),
        "stopped": _STOP.is_set(),
    }


def recover_orphans() -> int:
    """Re-queue jobs left mid-flight by a process restart.

    Without this, a crash strands jobs in `generating` forever and the UI
    shows work that no worker is doing.
    """
    orphaned = db.fetch_all(
        "SELECT id, attempts, max_attempts FROM generation_job "
        "WHERE status IN (?,?,?)",
        (JobState.PREPARING.value, JobState.GENERATING.value,
         JobState.PROCESSING.value))

    requeued = 0
    for job in orphaned:
        if job["attempts"] >= job["max_attempts"]:
            _finish(job["id"], JobState.FAILED,
                    error="interrupted by a restart and out of retries")
            continue
        db.update("generation_job", job["id"], {
            "status": JobState.QUEUED.value,
            "stage": "re-queued after restart",
        })
        db.log_job(job["id"], "re-queued after process restart", "warn")
        requeued += 1
    return requeued
