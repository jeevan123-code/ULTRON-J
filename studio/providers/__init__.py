"""Provider adapters for LEBENX STUDIO.

Import `registry` to obtain providers — never instantiate an adapter class
directly, or you bypass the connected-only dispatch gate and per-workspace
configuration.
"""

from .base import (  # noqa: F401
    BaseProvider, Capabilities, CostEstimate, GenerationHandle,
    GenerationRequest, GenerationStatus, ImageGenerationProvider, JobState,
    MediaStorageProvider, NotConnected, ProviderError, ProviderStatus,
    RateLimited, TERMINAL_STATES, UnsupportedCapability,
    VideoGenerationProvider, Voice, VoiceGenerationProvider,
)
