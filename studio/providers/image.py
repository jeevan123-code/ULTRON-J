"""
studio/providers/image.py — Image generation adapters.

Three adapters ship here. Each declares only what it was written against,
and each implements `verify_connection()` so the settings screen can show
proven reachability instead of an assumption:

  OpenAIImageProvider    OPENAI_API_KEY. Synchronous /v1/images/generations.
  TogetherImageProvider  TOGETHER_API_KEY. Synchronous, FLUX family.
  PollinationsProvider   No credentials. Free, best-effort, lower quality —
                         included so Studio Phase 2 is exercisable without
                         anyone holding a paid key.

All three are synchronous request/response APIs, so `generate_image()`
returns a handle already in a terminal state and stashes the bytes on it.
The job worker treats sync and async providers identically; only the
adapter knows the difference.

Model lists come from `capabilities()` but are treated as *defaults*, not
gospel: a caller may pass any model string through `GenerationRequest.model`
and the provider will forward it. We do not hard-fail on an unlisted model —
provider catalogues change faster than this file does — but we do not
silently substitute one either. The provider's own error is surfaced.
"""

from __future__ import annotations

import base64
from typing import Optional

from . import http
from .base import (
    Capabilities, CostEstimate, GenerationHandle, GenerationRequest,
    GenerationStatus, ImageGenerationProvider, JobState, ProviderError,
)

try:
    from config import OPENAI_API_KEY, TOGETHER_API_KEY
except ImportError:  # pragma: no cover
    import os
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip() or None
    TOGETHER_API_KEY = os.environ.get("TOGETHER_API_KEY", "").strip() or None


# Aspect ratio -> pixel size, per provider. Kept as explicit tables because
# each provider accepts a different discrete set; we never invent a size the
# provider has not documented.
_OPENAI_SIZES = {
    "1:1": "1024x1024",
    "16:9": "1536x1024",
    "9:16": "1024x1536",
}
_TOGETHER_SIZES = {
    "1:1": (1024, 1024),
    "16:9": (1344, 768),
    "9:16": (768, 1344),
}


def _sync_handle(status: GenerationStatus) -> GenerationHandle:
    """Wrap a completed synchronous result as a handle the worker can poll
    once. `_sync_result` is read back by `get_generation_status()`."""
    handle = GenerationHandle(external_id="", state=status.state)
    handle.raw["_sync_result"] = status
    return handle


class _SyncImageProvider(ImageGenerationProvider):
    """Shared behaviour for synchronous image APIs."""

    def get_generation_status(self, handle: GenerationHandle) -> GenerationStatus:
        result = handle.raw.get("_sync_result")
        if isinstance(result, GenerationStatus):
            return result
        return GenerationStatus(
            state=JobState.FAILED,
            error="no result recorded for this synchronous generation",
        )


# =============================================================================
# OPENAI
# =============================================================================

class OpenAIImageProvider(_SyncImageProvider):
    name = "openai"
    label = "OpenAI Images"
    credential_env = ("OPENAI_API_KEY",)
    docs_url = "https://platform.openai.com/docs/api-reference/images"

    ENDPOINT = "https://api.openai.com/v1/images/generations"
    MODELS_ENDPOINT = "https://api.openai.com/v1/models"

    def _key(self) -> Optional[str]:
        return self.settings.get("api_key") or OPENAI_API_KEY

    def is_connected(self) -> bool:
        return bool(self._key())

    def capabilities(self) -> Capabilities:
        return Capabilities(
            models=["gpt-image-1", "dall-e-3"],
            aspect_ratios=list(_OPENAI_SIZES),
            resolutions=sorted(set(_OPENAI_SIZES.values())),
            max_variations=4,
            text_to_image=True,
            # The images endpoint takes no negative_prompt and no seed.
            negative_prompt=False,
            seed_control=False,
            character_reference=False,
            cancellation=False,      # synchronous; nothing to cancel
            reports_progress=False,  # returns once, with no progress stream
            cost_estimation=False,
            notes="Synchronous endpoint. Negative prompts and seeds are not "
                  "supported — style must be expressed in the prompt itself.",
        )

    def verify_connection(self) -> dict:
        base = super().verify_connection()
        if base.get("error") and "not connected" in base["error"]:
            return base
        try:
            data = http.get_json(
                self.MODELS_ENDPOINT, provider=self.name,
                headers={"Authorization": f"Bearer {self._key()}"},
                timeout=(10, 30),
            )
            names = [m.get("id", "") for m in data.get("data", [])]
            image_models = [n for n in names if "image" in n or n.startswith("dall-e")]
            return {"ok": True, "verified": True, "models_seen": image_models[:20]}
        except ProviderError as exc:
            self._last_error = exc.message
            return {"ok": False, "verified": False, "error": exc.message}

    def generate_image(self, request: GenerationRequest) -> GenerationHandle:
        self._require_connected()
        model = request.model or "gpt-image-1"
        size = request.resolution or _OPENAI_SIZES.get(request.aspect_ratio, "1024x1024")

        payload = {
            "model": model,
            "prompt": request.prompt,
            "n": max(1, min(int(request.variations or 1), 4)),
            "size": size,
        }
        # dall-e-3 accepts only n=1; sending more is a hard 400.
        if model == "dall-e-3":
            payload["n"] = 1

        data = http.post_json(
            self.ENDPOINT, provider=self.name,
            headers={"Authorization": f"Bearer {self._key()}",
                     "Content-Type": "application/json"},
            json=payload, timeout=(10, 180),
        )

        entries = data.get("data") or []
        if not entries:
            return _sync_handle(GenerationStatus(
                state=JobState.FAILED, error="provider returned no image data"))

        urls: list[str] = []
        blob: Optional[bytes] = None
        for entry in entries:
            if entry.get("b64_json") and blob is None:
                try:
                    blob = base64.b64decode(entry["b64_json"])
                except Exception:  # noqa: BLE001
                    blob = None
            if entry.get("url"):
                urls.append(entry["url"])

        if blob is None and urls:
            blob, _ = http.download(urls[0], provider=self.name)

        if blob is None:
            return _sync_handle(GenerationStatus(
                state=JobState.FAILED,
                error="provider returned neither b64_json nor a fetchable url"))

        width, height = _parse_size(size)
        return _sync_handle(GenerationStatus(
            state=JobState.COMPLETED, output_urls=urls, output_bytes=blob,
            mime="image/png", width=width, height=height,
            stage="completed", raw={"model": model},
        ))


# =============================================================================
# TOGETHER AI
# =============================================================================

class TogetherImageProvider(_SyncImageProvider):
    name = "together"
    label = "Together AI (FLUX)"
    credential_env = ("TOGETHER_API_KEY",)
    docs_url = "https://docs.together.ai/reference/post-images-generations"

    ENDPOINT = "https://api.together.xyz/v1/images/generations"
    MODELS_ENDPOINT = "https://api.together.xyz/v1/models"

    def _key(self) -> Optional[str]:
        return self.settings.get("api_key") or TOGETHER_API_KEY

    def is_connected(self) -> bool:
        return bool(self._key())

    def capabilities(self) -> Capabilities:
        return Capabilities(
            models=[
                "black-forest-labs/FLUX.1-schnell",
                "black-forest-labs/FLUX.1-dev",
            ],
            aspect_ratios=list(_TOGETHER_SIZES),
            resolutions=[f"{w}x{h}" for w, h in _TOGETHER_SIZES.values()],
            max_variations=4,
            text_to_image=True,
            negative_prompt=True,
            seed_control=True,
            character_reference=False,
            cancellation=False,
            reports_progress=False,
            cost_estimation=False,
            notes="Synchronous. FLUX.1-schnell is the fast/cheap default; "
                  "FLUX.1-dev trades latency for fidelity.",
        )

    def verify_connection(self) -> dict:
        base = super().verify_connection()
        if base.get("error") and "not connected" in base["error"]:
            return base
        try:
            data = http.get_json(
                self.MODELS_ENDPOINT, provider=self.name,
                headers={"Authorization": f"Bearer {self._key()}"},
                timeout=(10, 30),
            )
            rows = data if isinstance(data, list) else data.get("data", [])
            names = [r.get("id", "") for r in rows if isinstance(r, dict)]
            return {"ok": True, "verified": True,
                    "models_seen": [n for n in names if "FLUX" in n][:20]}
        except ProviderError as exc:
            self._last_error = exc.message
            return {"ok": False, "verified": False, "error": exc.message}

    def generate_image(self, request: GenerationRequest) -> GenerationHandle:
        self._require_connected()
        model = request.model or "black-forest-labs/FLUX.1-schnell"
        width, height = _TOGETHER_SIZES.get(request.aspect_ratio, (1024, 1024))
        if request.resolution:
            width, height = _parse_size(request.resolution) or (width, height)

        payload = {
            "model": model,
            "prompt": request.prompt,
            "width": width,
            "height": height,
            "n": max(1, min(int(request.variations or 1), 4)),
            "response_format": "b64_json",
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            payload["seed"] = int(request.seed)

        data = http.post_json(
            self.ENDPOINT, provider=self.name,
            headers={"Authorization": f"Bearer {self._key()}",
                     "Content-Type": "application/json"},
            json=payload, timeout=(10, 180),
        )

        entries = data.get("data") or []
        if not entries:
            return _sync_handle(GenerationStatus(
                state=JobState.FAILED, error="provider returned no image data"))

        first = entries[0]
        blob: Optional[bytes] = None
        if first.get("b64_json"):
            blob = base64.b64decode(first["b64_json"])
        elif first.get("url"):
            blob, _ = http.download(first["url"], provider=self.name)

        if blob is None:
            return _sync_handle(GenerationStatus(
                state=JobState.FAILED, error="no decodable image in response"))

        return _sync_handle(GenerationStatus(
            state=JobState.COMPLETED, output_bytes=blob, mime="image/png",
            width=width, height=height, stage="completed", raw={"model": model},
        ))


# =============================================================================
# POLLINATIONS (no credentials)
# =============================================================================

class PollinationsImageProvider(_SyncImageProvider):
    """Free, keyless image endpoint.

    Included so that the whole Phase-2 asset pipeline can be exercised end to
    end with no paid account. It is genuinely lower quality and has no
    availability guarantee, which `capabilities().notes` states plainly so the
    UI can warn rather than over-promise.
    """

    name = "pollinations"
    label = "Pollinations (free, no key)"
    credential_env = ()
    docs_url = "https://pollinations.ai"

    ENDPOINT = "https://image.pollinations.ai/prompt/"

    def is_connected(self) -> bool:
        # No credentials required, so availability *is* connectedness.
        return http.REQUESTS_AVAILABLE

    def is_installed(self) -> bool:
        return http.REQUESTS_AVAILABLE

    def capabilities(self) -> Capabilities:
        return Capabilities(
            models=["flux", "turbo"],
            aspect_ratios=["1:1", "16:9", "9:16"],
            resolutions=["1024x1024", "1280x720", "720x1280"],
            max_variations=1,
            text_to_image=True,
            negative_prompt=False,
            seed_control=True,
            cancellation=False,
            reports_progress=False,
            notes="Free community endpoint — no uptime, rate-limit, or "
                  "consistency guarantees. Not suitable for production work.",
        )

    def verify_connection(self) -> dict:
        if not http.REQUESTS_AVAILABLE:
            return {"ok": False, "verified": False, "error": "requests not installed"}
        try:
            http.request("GET", self.ENDPOINT + "connectivity%20test",
                         provider=self.name, timeout=(10, 45),
                         params={"width": 64, "height": 64, "nologo": "true"})
            return {"ok": True, "verified": True, "models_seen": ["flux"]}
        except ProviderError as exc:
            self._last_error = exc.message
            return {"ok": False, "verified": False, "error": exc.message}

    def estimate_cost(self, request: GenerationRequest) -> CostEstimate:
        return CostEstimate(amount=0.0, confidence="published",
                            basis="free endpoint, no billing")

    def generate_image(self, request: GenerationRequest) -> GenerationHandle:
        from urllib.parse import quote, urlencode

        sizes = {"1:1": (1024, 1024), "16:9": (1280, 720), "9:16": (720, 1280)}
        width, height = sizes.get(request.aspect_ratio, (1024, 1024))

        params = {
            "width": width, "height": height,
            "model": request.model or "flux", "nologo": "true",
        }
        if request.seed is not None:
            params["seed"] = int(request.seed)

        url = (self.ENDPOINT + quote(request.prompt[:1800], safe="")
               + "?" + urlencode(params))
        blob, mime = http.download(url, provider=self.name, timeout=(10, 180))
        if not blob:
            return _sync_handle(GenerationStatus(
                state=JobState.FAILED, error="empty response from endpoint"))

        return _sync_handle(GenerationStatus(
            state=JobState.COMPLETED, output_bytes=blob,
            mime=mime or "image/jpeg", width=width, height=height,
            stage="completed",
        ))


def _parse_size(size: str):
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return None, None


IMAGE_PROVIDERS = [OpenAIImageProvider, TogetherImageProvider, PollinationsImageProvider]
