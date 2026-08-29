"""
studio/providers/base.py — Provider abstraction for LEBENX STUDIO.

The single most important contract in the Studio: **a provider may only
report a capability it can actually perform right now.**

Four distinct states, never collapsed into a boolean:

    AVAILABLE            an adapter for this provider is compiled in, but
                         it has no credentials — it cannot generate.
    MISSING_CREDENTIALS  same as above, stated from the user's angle: the
                         env var the adapter needs is unset.
    UNAVAILABLE          the adapter's runtime dependency is not installed
                         (e.g. no `requests`, no ffmpeg) — installing a key
                         will not help.
    CONNECTED            credentials present and the adapter is ready to
                         accept work. Only CONNECTED providers may be
                         dispatched to.

`ProviderRegistry.dispatchable()` is the only way jobs pick a provider, and
it filters on CONNECTED. There is deliberately no code path that returns a
synthetic asset, a placeholder URL, or a fabricated progress percentage when
no provider is connected — a job with no provider fails with a plain reason.

Normalisation vs. capability preservation
-----------------------------------------
The internal API is normalised (one `generate_image()` shape for every image
provider), but capabilities are *not* flattened: `Capabilities` records what
each provider genuinely supports — resolutions, durations, aspect ratios,
whether it can do image-to-video, whether it offers any character-consistency
mechanism. Callers ask before they assume. `supports()` returns False for
anything a provider has not explicitly declared.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


# =============================================================================
# STATES
# =============================================================================

class ProviderStatus(str, Enum):
    CONNECTED = "connected"
    AVAILABLE = "available"
    MISSING_CREDENTIALS = "missing_credentials"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class JobState(str, Enum):
    """Normalised generation-job lifecycle.

    Provider adapters map their own vocabulary onto these via
    `map_status()`. Any provider state the adapter does not recognise maps
    to FAILED with the raw value preserved in the error — never to a
    silently optimistic COMPLETED.
    """
    DRAFT = "draft"
    QUEUED = "queued"
    PREPARING = "preparing"
    GENERATING = "generating"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


# =============================================================================
# ERRORS
# =============================================================================

class ProviderError(Exception):
    """Base class. `retryable` drives the job worker's retry decision."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int = 0):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


class NotConnected(ProviderError):
    """Raised when a provider is dispatched to without credentials. Never
    retryable — retrying cannot conjure an API key."""

    def __init__(self, provider: str, requirement: str = ""):
        msg = f"provider '{provider}' is not connected"
        if requirement:
            msg += f" (set {requirement})"
        super().__init__(msg, retryable=False)


class RateLimited(ProviderError):
    def __init__(self, provider: str, retry_after: float = 0.0):
        super().__init__(f"provider '{provider}' rate-limited", retryable=True, status_code=429)
        self.retry_after = retry_after


class UnsupportedCapability(ProviderError):
    """The provider is connected but genuinely cannot do what was asked."""

    def __init__(self, provider: str, capability: str):
        super().__init__(f"provider '{provider}' does not support {capability}", retryable=False)


# =============================================================================
# CAPABILITIES
# =============================================================================

@dataclass
class Capabilities:
    """What a provider actually supports. Empty collections mean "not
    declared", which callers must read as "not supported"."""

    models: list[str] = field(default_factory=list)
    aspect_ratios: list[str] = field(default_factory=list)
    resolutions: list[str] = field(default_factory=list)
    durations_s: list[float] = field(default_factory=list)
    max_variations: int = 1
    languages: list[str] = field(default_factory=list)

    text_to_image: bool = False
    text_to_video: bool = False
    image_to_video: bool = False
    negative_prompt: bool = False
    seed_control: bool = False
    # True only where the provider documents an identity/consistency
    # mechanism (reference image, character token). Best-effort even then —
    # the UI must never promise perfect identity match.
    character_reference: bool = False
    cancellation: bool = False
    # True when the provider returns real numeric progress. When False the
    # UI shows a named stage instead of a percentage.
    reports_progress: bool = False
    cost_estimation: bool = False

    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GenerationRequest:
    """Normalised request. Provider-specific extras ride in `extra` and are
    interpreted only by the adapter that declared them."""

    prompt: str
    negative_prompt: str = ""
    model: str = ""
    aspect_ratio: str = "16:9"
    resolution: str = ""
    duration_s: float = 0.0
    variations: int = 1
    seed: Optional[int] = None
    image_url: str = ""          # image-to-video / img2img source
    image_path: str = ""
    reference_asset_paths: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class GenerationHandle:
    """Returned by an async `generate_*`. `external_id` is the provider's
    own job id, which `get_generation_status()` polls."""

    external_id: str
    state: JobState = JobState.QUEUED
    raw: dict = field(default_factory=dict)


@dataclass
class GenerationStatus:
    """A status snapshot. `progress_pct` stays None unless the provider
    genuinely reported a number — the UI renders a stage name in that case
    rather than inventing a percentage."""

    state: JobState
    progress_pct: Optional[float] = None
    stage: str = ""
    output_urls: list[str] = field(default_factory=list)
    output_bytes: Optional[bytes] = None
    mime: str = ""
    duration_s: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    actual_cost: Optional[float] = None
    error: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def to_dict(self) -> dict:
        out = asdict(self)
        out.pop("output_bytes", None)
        out["state"] = self.state.value
        out["has_bytes"] = self.output_bytes is not None
        return out


@dataclass
class CostEstimate:
    """Always an *estimate*. `confidence` is surfaced verbatim in the UI so
    a modelled guess is never displayed as a guaranteed price."""

    amount: Optional[float]
    currency: str = "USD"
    confidence: str = "unknown"   # published|modelled|unknown
    basis: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Voice:
    id: str
    name: str
    language: str = "en"
    gender: str = ""
    preview_url: str = ""
    provider: str = ""


# =============================================================================
# BASE PROVIDER
# =============================================================================

class BaseProvider(abc.ABC):
    """Common surface for every provider kind."""

    #: stable machine name, unique within a kind
    name: str = "base"
    #: human label for the settings screen
    label: str = "Base Provider"
    #: image|video|voice|music|storage
    kind: str = "base"
    #: env var(s) the adapter needs; used to explain MISSING_CREDENTIALS
    credential_env: tuple[str, ...] = ()
    #: docs URL shown next to the connect button
    docs_url: str = ""

    def __init__(self, **settings):
        self.settings = settings or {}
        self._last_error = ""

    # -- state ---------------------------------------------------------------

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """True only when this adapter can accept work *right now*."""

    def is_installed(self) -> bool:
        """False when a runtime dependency is missing (no key will fix it)."""
        return True

    def status(self) -> ProviderStatus:
        if not self.is_installed():
            return ProviderStatus.UNAVAILABLE
        if self._last_error:
            return ProviderStatus.ERROR
        if self.is_connected():
            return ProviderStatus.CONNECTED
        return ProviderStatus.MISSING_CREDENTIALS if self.credential_env else ProviderStatus.AVAILABLE

    @abc.abstractmethod
    def capabilities(self) -> Capabilities:
        ...

    def supports(self, capability: str) -> bool:
        """Conservative capability probe — unknown means unsupported."""
        return bool(getattr(self.capabilities(), capability, False))

    def estimate_cost(self, request: GenerationRequest) -> CostEstimate:
        """Default: we do not know. Adapters override only where the
        provider publishes a rate we can apply."""
        return CostEstimate(amount=None, confidence="unknown",
                            basis="provider does not publish a usable rate")

    def verify_connection(self) -> dict:
        """Make a real, cheap call against the provider and report what
        happened.

        This exists because a declared capability is only a claim until an
        actual call proves it. `Capabilities` describes what the adapter was
        *written* against; `verify_connection()` is the only thing that
        establishes the provider is reachable with these credentials right
        now. The registry records the result and the settings UI shows
        "verified <time>" versus "declared, never verified" — it never
        presents an unverified adapter as proven.

        Adapters override with a genuine list-models / list-voices call.
        The default refuses to guess.
        """
        if not self.is_installed():
            return {"ok": False, "verified": False,
                    "error": "adapter dependency not installed"}
        if not self.is_connected():
            return {"ok": False, "verified": False,
                    "error": f"not connected; set {', '.join(self.credential_env) or 'credentials'}"}
        return {"ok": False, "verified": False,
                "error": "adapter does not implement a verification call"}

    def describe(self) -> dict:
        st = self.status()
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "status": st.value,
            "connected": st == ProviderStatus.CONNECTED,
            "credential_env": list(self.credential_env),
            "docs_url": self.docs_url,
            "capabilities": self.capabilities().to_dict(),
            "last_error": self._last_error,
        }

    # -- helpers for adapters ------------------------------------------------

    def _require_connected(self) -> None:
        if not self.is_connected():
            raise NotConnected(self.name, ", ".join(self.credential_env))

    def _require(self, capability: str) -> None:
        if not self.supports(capability):
            raise UnsupportedCapability(self.name, capability)

    @staticmethod
    def map_status(raw_state: str, mapping: dict[str, JobState]) -> JobState:
        """Map a provider's vocabulary onto `JobState`.

        An unrecognised value maps to FAILED, never to COMPLETED — an unknown
        state is a state we cannot vouch for.
        """
        return mapping.get((raw_state or "").lower().strip(), JobState.FAILED)


# =============================================================================
# KIND-SPECIFIC INTERFACES
# =============================================================================

class ImageGenerationProvider(BaseProvider):
    kind = "image"

    @abc.abstractmethod
    def generate_image(self, request: GenerationRequest) -> GenerationHandle:
        ...

    @abc.abstractmethod
    def get_generation_status(self, handle: GenerationHandle) -> GenerationStatus:
        ...

    def list_supported_models(self) -> list[str]:
        return list(self.capabilities().models)

    def cancel_generation(self, handle: GenerationHandle) -> bool:
        """Return False when the provider offers no cancellation API — the
        job worker then stops polling and marks the job cancelled locally,
        while making clear the remote work may still bill."""
        return False


class VideoGenerationProvider(BaseProvider):
    kind = "video"

    @abc.abstractmethod
    def generate_video(self, request: GenerationRequest) -> GenerationHandle:
        ...

    @abc.abstractmethod
    def get_generation_status(self, handle: GenerationHandle) -> GenerationStatus:
        ...

    def get_supported_models(self) -> list[str]:
        return list(self.capabilities().models)

    def get_supported_durations(self) -> list[float]:
        return list(self.capabilities().durations_s)

    def cancel_generation(self, handle: GenerationHandle) -> bool:
        return False


class VoiceGenerationProvider(BaseProvider):
    kind = "voice"

    @abc.abstractmethod
    def list_voices(self, language: str = "") -> list[Voice]:
        ...

    @abc.abstractmethod
    def generate_speech(self, text: str, voice_id: str = "", *,
                        language: str = "en", speed: float = 1.0,
                        **extra) -> GenerationStatus:
        """Synchronous for every adapter we ship: TTS returns in seconds, so
        the job worker calls this inside its own thread rather than polling.
        Returns a terminal `GenerationStatus` carrying audio bytes."""

    def get_generation_status(self, handle: GenerationHandle) -> GenerationStatus:
        """Only meaningful for providers with an async TTS endpoint."""
        return GenerationStatus(state=JobState.FAILED,
                                error="provider does not expose async speech status")


class MediaStorageProvider(abc.ABC):
    """Storage abstraction so local dev and object storage differ only here."""

    name = "base"

    @abc.abstractmethod
    def upload(self, key: str, data: bytes, mime: str = "") -> dict:
        ...

    @abc.abstractmethod
    def download_url(self, key: str, expires_s: int = 3600) -> str:
        ...

    @abc.abstractmethod
    def delete(self, key: str) -> bool:
        ...

    @abc.abstractmethod
    def get_metadata(self, key: str) -> Optional[dict]:
        ...

    def local_path(self, key: str) -> Optional[str]:
        """Path on disk when the backend has one — the renderer needs real
        paths to feed ffmpeg. Object-storage backends return None and the
        renderer stages a temp copy instead."""
        return None


__all__ = [
    "ProviderStatus", "JobState", "TERMINAL_STATES",
    "ProviderError", "NotConnected", "RateLimited", "UnsupportedCapability",
    "Capabilities", "GenerationRequest", "GenerationHandle", "GenerationStatus",
    "CostEstimate", "Voice",
    "BaseProvider", "ImageGenerationProvider", "VideoGenerationProvider",
    "VoiceGenerationProvider", "MediaStorageProvider",
]
