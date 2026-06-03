"""
auth.py — App-wide API-key gate for Ultron-J.

Why this exists: app.py exposes ~200 endpoints across 7 blueprints —
file read/write, shell execution, computer control, phone ADB control,
and /self_upgrade/run (which rewrites code). Before this gate any
device on the LAN that could reach the Flask port could call them.

The gate enforces one of three modes, in order:

  1. CORS preflight (`OPTIONS`)            -> always allowed.
  2. Explicit public path                   -> always allowed (UI shell,
     health check, Flask /static/*).
  3. `ULTRON_API_KEYS` env var IS set       -> require `X-API-Key`
     header (or `?api_key=` query param) to match one of the keys.
     Mismatch -> 401.
  4. `ULTRON_API_KEYS` env var NOT set      -> "dev mode". Loopback
     requests (127.0.0.1 / ::1) pass; remote requests get 403 with
     a message explaining how to enable remote access.

This matches the master-prompt rule "never weaken an existing
safety check — only add". There was no gate before; this is purely
additive.

Configuration (all env vars, no code changes needed to retune):

  ULTRON_API_KEYS              comma-separated list of accepted keys
  ULTRON_PUBLIC_PATHS          comma-separated extra paths to whitelist
                               (e.g. "/voice,/admin"). Static files
                               under /static/ are always public.
"""

import os
from flask import request, jsonify

from config import ULTRON_API_KEYS


# Default public paths — the UI shell, the health check, and CORS preflight.
# Extend via ULTRON_PUBLIC_PATHS env var (no code edit needed).
_BASE_PUBLIC = {"/", "/health"}
_EXTRA_PUBLIC = {
    p.strip()
    for p in os.environ.get("ULTRON_PUBLIC_PATHS", "").split(",")
    if p.strip()
}
PUBLIC_PATHS: set[str] = _BASE_PUBLIC | _EXTRA_PUBLIC

# Path prefixes that are always public (Flask static asset serving).
PUBLIC_PREFIXES: tuple[str, ...] = ("/static/",)


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def install_auth(app) -> None:
    """Register the before_request guard. Call once, right after the
    Flask app is constructed (in app.py)."""

    @app.before_request
    def _ultron_auth_guard():
        # CORS preflight — never gate. The CORS extension handles the
        # actual Origin/Method check.
        if request.method == "OPTIONS":
            return None

        if _is_public(request.path):
            return None

        # No keys configured -> dev mode. Loopback only; refuse remote.
        if not ULTRON_API_KEYS:
            remote = request.remote_addr or ""
            if remote not in ("127.0.0.1", "::1"):
                return (
                    jsonify(
                        {
                            "error": "no API keys set; remote access disabled",
                            "hint": "set ULTRON_API_KEYS in .env and resend "
                                    "with X-API-Key header",
                        }
                    ),
                    403,
                )
            return None

        # Keys configured -> require a match.
        key = (
            request.headers.get("X-API-Key")
            or request.args.get("api_key")
        )
        if key not in ULTRON_API_KEYS:
            return jsonify({"error": "unauthorized"}), 401

        return None
