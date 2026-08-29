"""
studio/providers/video.py — Video generation adapters.

Video generation is the one part of the pipeline that is unavoidably
asynchronous: a clip takes minutes, so the request/response cycle cannot
hold it. Every adapter here returns a `GenerationHandle` carrying the
provider's own job id, and the Studio job worker polls
`get_generation_status()` on its own thread.

Shipped adapter
---------------
`ReplicateVideoProvider` targets Replicate's generic predictions API, which
is model-agnostic: the *model version* decides whether text-to-video,
image-to-video, or neither is available. That is why this adapter refuses
to hardcode a model catalogue — `capabilities().models` is populated from
configuration, and the durations/resolutions it reports are whatever the
operator recorded for the version they configured.

This is the honest shape for a model-broker API. An adapter that claimed
"Replicate supports 5-second 1080p image-to-video" would be asserting
something only true of particular versions.

Adding a provider
-----------------
Subclass `VideoGenerationProvider`, declare `credential_env`, implement
`generate_video`, `get_generation_status`, `capabilities`, and ideally
`cancel_generation` and `verify_connection`. Register the class in
`registry.py`. Nothing else in the Studio needs to change — the job worker,
cost centre, storyboard, and timeline all speak the normalised interface.
"""

from __future__ import annotations

from typing import Optional

from . import http
from .base import (
    Capabilities, CostEstimate, GenerationHandle, GenerationRequest,
    GenerationStatus, JobState, ProviderError, UnsupportedCapability,
    VideoGenerationProvider,
)

try:
    from config import REPLICATE_API_TOKEN
except ImportError:  # pragma: no cover
    import os
    REPLICATE_API_TOKEN = (os.environ.get("REPLICATE_API_TOKEN", "").strip()
                           or os.environ.get("REPLICATE_API_KEY", "").strip() or None)


class ReplicateVideoProvider(VideoGenerationProvider):
    """Replicate predictions API.

    Status vocabulary is mapped explicitly. An unrecognised status becomes
    FAILED rather than being optimistically treated as still-running or
    complete — see `BaseProvider.map_status`.
    """

    name = "replicate"
    label = "Replicate (video models)"
    credential_env = ("REPLICATE_API_TOKEN",)
    docs_url = "https://replicate.com/docs/reference/http"

    BASE = "https://api.replicate.com/v1"

    STATUS_MAP = {
        "starting": JobState.PREPARING,
        "processing": JobState.GENERATING,
        "succeeded": JobState.COMPLETED,
        "failed": JobState.FAILED,
        "canceled": JobState.CANCELLED,
        "cancelled": JobState.CANCELLED,
    }

    def _key(self) -> Optional[str]:
        return self.settings.get("api_key") or REPLICATE_API_TOKEN

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._key()}",
                "Content-Type": "application/json"}

    def is_connected(self) -> bool:
        return bool(self._key())

    def capabilities(self) -> Capabilities:
        """Reported from configuration, because on a model-broker the model
        determines the capability. Operators record what the version they
        configured actually supports; we report nothing we were not told."""
        cfg = self.settings or {}
        models = [m for m in (cfg.get("models") or []) if m]
        return Capabilities(
            models=models,
            aspect_ratios=cfg.get("aspect_ratios") or [],
            resolutions=cfg.get("resolutions") or [],
            durations_s=[float(d) for d in (cfg.get("durations_s") or [])],
            max_variations=1,
            text_to_video=bool(cfg.get("text_to_video", bool(models))),
            image_to_video=bool(cfg.get("image_to_video", False)),
            negative_prompt=bool(cfg.get("negative_prompt", False)),
            seed_control=bool(cfg.get("seed_control", True)),
            character_reference=bool(cfg.get("character_reference", False)),
            cancellation=True,        # /predictions/{id}/cancel is generic
            reports_progress=False,   # predictions expose logs, not a percentage
            cost_estimation=False,
            notes=(
                "Model-broker API: capabilities depend entirely on the model "
                "version configured. Configure models and their supported "
                "durations in Studio Settings — this adapter reports only what "
                "it was told, and claims nothing about versions it has not seen."
            ),
        )

    def verify_connection(self) -> dict:
        base = super().verify_connection()
        if base.get("error") and "not connected" in base["error"]:
            return base
        try:
            # Cheapest authenticated read that proves the token works.
            http.get_json(f"{self.BASE}/account", provider=self.name,
                          headers=self._headers(), timeout=(10, 30))
            return {"ok": True, "verified": True,
                    "models_seen": list(self.capabilities().models)}
        except ProviderError as exc:
            self._last_error = exc.message
            return {"ok": False, "verified": False, "error": exc.message}

    # -- generation ----------------------------------------------------------

    def generate_video(self, request: GenerationRequest) -> GenerationHandle:
        self._require_connected()

        version = request.model or (self.settings.get("default_model") or "")
        if not version:
            raise UnsupportedCapability(
                self.name,
                "video generation without a configured model version "
                "(set one in Studio Settings)",
            )

        if request.image_url or request.image_path:
            self._require("image_to_video")

        payload_input = {"prompt": request.prompt}
        if request.negative_prompt and self.supports("negative_prompt"):
            payload_input["negative_prompt"] = request.negative_prompt
        if request.duration_s:
            payload_input["duration"] = request.duration_s
        if request.aspect_ratio:
            payload_input["aspect_ratio"] = request.aspect_ratio
        if request.seed is not None and self.supports("seed_control"):
            payload_input["seed"] = int(request.seed)
        if request.image_url:
            # Parameter name varies by model version; the operator maps it.
            key = self.settings.get("image_input_key", "image")
            payload_input[key] = request.image_url
        payload_input.update(request.extra or {})

        body = {"input": payload_input}
        # A bare model slug uses the model-scoped endpoint; a 64-hex string is
        # a pinned version for the generic endpoint.
        if _looks_like_version_hash(version):
            body["version"] = version
            url = f"{self.BASE}/predictions"
        else:
            url = f"{self.BASE}/models/{version}/predictions"

        data = http.post_json(url, provider=self.name, headers=self._headers(),
                              json=body, timeout=(10, 60))

        external_id = data.get("id") or ""
        if not external_id:
            raise ProviderError(f"{self.name}: prediction response had no id",
                                retryable=False)

        return GenerationHandle(
            external_id=external_id,
            state=self.map_status(data.get("status", ""), self.STATUS_MAP),
            raw={"urls": data.get("urls", {}), "model": version},
        )

    def get_generation_status(self, handle: GenerationHandle) -> GenerationStatus:
        self._require_connected()
        data = http.get_json(
            f"{self.BASE}/predictions/{handle.external_id}",
            provider=self.name, headers=self._headers(), timeout=(10, 45),
        )

        raw_status = data.get("status", "")
        state = self.map_status(raw_status, self.STATUS_MAP)

        if state == JobState.FAILED and raw_status.lower() not in self.STATUS_MAP:
            # Preserve the unmapped value instead of guessing at its meaning.
            return GenerationStatus(
                state=JobState.FAILED,
                error=f"unrecognised provider status '{raw_status}'",
                raw=data,
            )

        urls = _extract_output_urls(data.get("output"))
        metrics = data.get("metrics") or {}

        return GenerationStatus(
            state=state,
            # Replicate exposes log text, not a percentage. Reporting a stage
            # name is truthful; a synthesised percentage would not be.
            progress_pct=None,
            stage=raw_status,
            output_urls=urls,
            mime="video/mp4" if urls else "",
            error=str(data.get("error") or ""),
            actual_cost=_safe_float(metrics.get("predict_time_cost")),
            raw={"metrics": metrics},
        )

    def cancel_generation(self, handle: GenerationHandle) -> bool:
        if not handle.external_id or not self.is_connected():
            return False
        try:
            http.post_json(
                f"{self.BASE}/predictions/{handle.external_id}/cancel",
                provider=self.name, headers=self._headers(), timeout=(10, 30),
            )
            return True
        except ProviderError:
            return False

    def estimate_cost(self, request: GenerationRequest) -> CostEstimate:
        """Replicate bills by compute-seconds consumed, which is not knowable
        before the run. Rather than print a number we cannot stand behind, we
        surface the operator's own configured rate when they set one."""
        rate = self.settings.get("usd_per_second_of_output")
        if rate and request.duration_s:
            return CostEstimate(
                amount=round(float(rate) * float(request.duration_s), 4),
                confidence="modelled",
                basis=f"operator-configured rate {rate} USD per output second",
            )
        return CostEstimate(
            amount=None, confidence="unknown",
            basis="billed by compute time; not predictable before the run",
        )


def _looks_like_version_hash(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def _extract_output_urls(output) -> list[str]:
    """Prediction output is model-shaped: a URL, a list, or an object."""
    if not output:
        return []
    if isinstance(output, str):
        return [output]
    if isinstance(output, list):
        return [o for o in output if isinstance(o, str)]
    if isinstance(output, dict):
        for key in ("video", "url", "output", "mp4"):
            val = output.get(key)
            if isinstance(val, str):
                return [val]
            if isinstance(val, list):
                return [v for v in val if isinstance(v, str)]
    return []


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


VIDEO_PROVIDERS = [ReplicateVideoProvider]
