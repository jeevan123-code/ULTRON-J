"""
studio/providers/registry.py — Provider discovery and dispatch.

The registry is the only way the rest of the Studio obtains a provider. It
enforces the rule that makes the whole system trustworthy:

    dispatchable(kind) returns ONLY providers that are CONNECTED.

There is no fallback that fabricates output when nothing is connected. A job
asking for an image with no connected image provider fails with
"no connected image provider", which the UI shows as a blocked scene with a
Connect Provider action — not as a placeholder image or a spinning bar.

Per-workspace configuration (enabled flag, default model, adapter settings)
lives in the `provider_configuration` table and is merged onto the adapter at
construction time, so one workspace can pin a Replicate model version without
affecting another.

Verification state
------------------
`verify(kind, name)` performs a real call and stores the outcome in the
provider's configuration row. `describe_all()` reports `verified_at` and
`verified_ok` so the settings screen distinguishes "declared support" from
"we called it and it answered".
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from .. import db
from .base import (
    BaseProvider, ImageGenerationProvider, ProviderStatus,
    VideoGenerationProvider, VoiceGenerationProvider,
)
from .image import IMAGE_PROVIDERS
from .video import VIDEO_PROVIDERS
from .voice import VOICE_PROVIDERS

#: kind -> {name: class}
_CLASSES: dict[str, dict[str, type[BaseProvider]]] = {
    "image": {cls.name: cls for cls in IMAGE_PROVIDERS},
    "video": {cls.name: cls for cls in VIDEO_PROVIDERS},
    "voice": {cls.name: cls for cls in VOICE_PROVIDERS},
}

_LOCK = threading.Lock()


class NoProviderAvailable(Exception):
    """Raised when work is requested and nothing is connected to do it.

    Carries the full picture so the UI can render an actionable message
    rather than a bare failure.
    """

    def __init__(self, kind: str, detail: str = "", candidates: Optional[list] = None):
        self.kind = kind
        self.candidates = candidates or []
        message = detail or f"no connected {kind} provider"
        super().__init__(message)
        self.message = message


# =============================================================================
# CONFIGURATION
# =============================================================================

def _config_row(workspace: str, kind: str, provider: str) -> Optional[dict]:
    return db.fetch_one(
        "SELECT * FROM provider_configuration WHERE workspace=? AND kind=? AND provider=?",
        (workspace, kind, provider), json_fields=("settings",),
    )


def get_config(workspace: str, kind: str, provider: str) -> dict:
    row = _config_row(workspace, kind, provider)
    if not row:
        return {"enabled": True, "default_model": "", "settings": {}}
    return {
        "enabled": bool(row["enabled"]),
        "default_model": row["default_model"] or "",
        "settings": row["settings"] or {},
    }


def set_config(workspace: str, kind: str, provider: str, *,
               enabled: Optional[bool] = None,
               default_model: Optional[str] = None,
               settings: Optional[dict] = None) -> dict:
    """Upsert a provider's per-workspace configuration.

    Secrets note: `settings` may legitimately hold an `api_key` for operators
    who prefer per-workspace keys over process-wide env vars. It is stored
    server-side and never returned by `describe_all()` — see `_redact()`.
    """
    if kind not in _CLASSES:
        raise ValueError(f"unknown provider kind '{kind}'")
    if provider not in _CLASSES[kind]:
        raise ValueError(f"unknown {kind} provider '{provider}'")

    existing = _config_row(workspace, kind, provider)
    now = db.now()

    if existing:
        patch: dict = {}
        if enabled is not None:
            patch["enabled"] = 1 if enabled else 0
        if default_model is not None:
            patch["default_model"] = default_model
        if settings is not None:
            merged = dict(existing["settings"] or {})
            merged.update(settings)
            # An empty string clears a key rather than storing a blank secret.
            merged = {k: v for k, v in merged.items() if v not in ("", None)}
            patch["settings"] = db._dumps(merged)
        db.update("provider_configuration", existing["id"], patch)
    else:
        db.insert("provider_configuration", {
            "id": db.new_id("pcfg"),
            "workspace": workspace,
            "kind": kind,
            "provider": provider,
            "enabled": 1 if (enabled is None or enabled) else 0,
            "default_model": default_model or "",
            "settings": db._dumps(settings or {}),
            "created_at": now,
            "updated_at": now,
        })

    return get_config(workspace, kind, provider)


# =============================================================================
# CONSTRUCTION
# =============================================================================

def build(kind: str, name: str, workspace: str = "default") -> BaseProvider:
    """Construct an adapter with its workspace configuration applied."""
    classes = _CLASSES.get(kind)
    if not classes:
        raise ValueError(f"unknown provider kind '{kind}'")
    cls = classes.get(name)
    if cls is None:
        raise ValueError(f"unknown {kind} provider '{name}'")

    cfg = get_config(workspace, kind, name)
    settings = dict(cfg["settings"] or {})
    if cfg["default_model"]:
        settings.setdefault("default_model", cfg["default_model"])
    return cls(**settings)


def all_providers(kind: str, workspace: str = "default") -> list[BaseProvider]:
    return [build(kind, name, workspace) for name in _CLASSES.get(kind, {})]


def dispatchable(kind: str, workspace: str = "default") -> list[BaseProvider]:
    """Providers that may actually receive work: connected AND enabled.

    This is the gate. Nothing outside the registry decides that a provider
    is usable.
    """
    out = []
    for name, _cls in _CLASSES.get(kind, {}).items():
        cfg = get_config(workspace, kind, name)
        if not cfg["enabled"]:
            continue
        provider = build(kind, name, workspace)
        if provider.status() == ProviderStatus.CONNECTED:
            out.append(provider)
    return out


def resolve(kind: str, workspace: str = "default", preferred: str = "",
            require: str = "") -> BaseProvider:
    """Pick the provider to run a job on.

    `preferred` wins when it is connected. `require` names a capability the
    provider must genuinely declare (e.g. "image_to_video"), so we never
    dispatch image-to-video work to a text-only model.

    Raises NoProviderAvailable — with the full candidate list and why each
    one was rejected — rather than degrading to something fake.
    """
    candidates = dispatchable(kind, workspace)

    if require:
        candidates = [p for p in candidates if p.supports(require)]

    if preferred:
        for provider in candidates:
            if provider.name == preferred:
                return provider

    if candidates:
        return candidates[0]

    # Nothing usable — explain precisely why, per provider.
    diagnosis = []
    for name in _CLASSES.get(kind, {}):
        provider = build(kind, name, workspace)
        cfg = get_config(workspace, kind, name)
        status = provider.status().value
        if not cfg["enabled"]:
            status = "disabled"
        elif require and status == ProviderStatus.CONNECTED.value and not provider.supports(require):
            status = f"connected but does not support {require}"
        diagnosis.append({
            "provider": name,
            "label": provider.label,
            "status": status,
            "credential_env": list(provider.credential_env),
        })

    detail = f"no connected {kind} provider"
    if require:
        detail += f" supporting {require}"
    raise NoProviderAvailable(kind, detail, diagnosis)


# =============================================================================
# VERIFICATION
# =============================================================================

def verify(kind: str, name: str, workspace: str = "default") -> dict:
    """Make a real call to the provider and record what happened.

    The stored result is what the settings UI reports. We never mark a
    provider verified on the strength of its own capability declaration.
    """
    provider = build(kind, name, workspace)
    with _LOCK:
        try:
            result = provider.verify_connection()
        except Exception as exc:  # noqa: BLE001 - verification must not raise
            result = {"ok": False, "verified": False, "error": str(exc)}

    set_config(workspace, kind, name, settings={
        "_verified_ok": bool(result.get("verified")),
        "_verified_at": time.time(),
        "_verified_error": str(result.get("error", ""))[:300],
    })
    result["provider"] = name
    result["kind"] = kind
    return result


def _redact(settings: dict) -> dict:
    """Strip secrets before any provider config crosses the wire.

    API keys are write-only from the client's perspective: they can be set,
    never read back. We report presence, not value.
    """
    safe = {}
    for key, value in (settings or {}).items():
        lowered = key.lower()
        if any(token in lowered for token in ("key", "token", "secret", "password")):
            safe[key] = "***set***" if value else ""
        else:
            safe[key] = value
    return safe


def describe_all(workspace: str = "default") -> dict:
    """Full provider picture for the settings screen."""
    out: dict = {}
    for kind in _CLASSES:
        entries = []
        for name in _CLASSES[kind]:
            provider = build(kind, name, workspace)
            cfg = get_config(workspace, kind, name)
            settings = cfg["settings"] or {}
            info = provider.describe()
            info.update({
                "enabled": cfg["enabled"],
                "default_model": cfg["default_model"],
                "settings": _redact({k: v for k, v in settings.items()
                                     if not k.startswith("_")}),
                "verified_ok": bool(settings.get("_verified_ok")),
                "verified_at": settings.get("_verified_at"),
                "verified_error": settings.get("_verified_error", ""),
            })
            # Anything never verified is labelled as a claim, not a fact.
            info["capability_confidence"] = (
                "verified" if info["verified_ok"] else "declared_unverified"
            )
            entries.append(info)
        out[kind] = entries

    from ..storage import describe_storage
    out["storage"] = describe_storage()
    return out


def register_provider(cls: type[BaseProvider]) -> None:
    """Register an adapter defined outside this package."""
    kind = getattr(cls, "kind", "")
    if kind not in _CLASSES:
        raise ValueError(f"cannot register provider of unknown kind '{kind}'")
    _CLASSES[kind][cls.name] = cls


def known_kinds() -> list[str]:
    return list(_CLASSES)


__all__ = [
    "build", "all_providers", "dispatchable", "resolve", "verify",
    "describe_all", "get_config", "set_config", "register_provider",
    "known_kinds", "NoProviderAvailable",
]
