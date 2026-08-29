"""
Phase 5 acceptance — route smoke test.

Iterate every Flask route registered across all 7 blueprints and send
a single GET or POST. The assertion is that NOTHING returns >=500.

Why <500 is the right gate:
  * 200 — handler ran and succeeded
  * 4xx — handler ran and refused (missing field, unauth, confirm
    needed, file not found) — that's working as designed
  * 5xx — uncaught exception in our code — a real bug

We deliberately do NOT assert 200 because most routes need request-
specific input we can't fabricate generically. The smoke test catches
regressions like "I broke an import and now /provider_health 500s on
every call".

Run:  venv/bin/python -m pytest tests/test_route_smoke.py -v --timeout=30
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module                       # noqa: E402
import auth                                     # noqa: E402


# Routes we deliberately skip — they require resources / interactive
# input that can't be safely fabricated in a unit test.
SKIP_ROUTES: set[str] = {
    # Long-running / network-dependent / cost-incurring on every hit
    "/intelligence/ask",       # streams; needs SSE client
    "/api/voice/chat",         # needs audio file
    "/api/voice/transcribe",   # needs audio file
    "/api/voice/stream_chat",  # streams
}


# Path-param substitutions. Flask routes like /self_modify/apply/<id>
# need a concrete value. Pick a safe placeholder per rule type.
PATH_PARAM_VALUES = {
    "string":  "test",
    "int":     "1",
    "path":    "test",
    "default": "test",
}


def _route_paths():
    """Yield (path, methods) for every registered rule. Substitutes
    safe placeholders into <type:name> path params."""
    for rule in app_module.app.url_map.iter_rules():
        path = str(rule.rule)
        # Substitute path params
        def _sub(m):
            type_ = m.group(1) or "default"
            return PATH_PARAM_VALUES.get(type_, PATH_PARAM_VALUES["default"])
        path = re.sub(r"<(?:(\w+):)?\w+>", _sub, path)
        if path in SKIP_ROUTES:
            continue
        methods = rule.methods or set()
        yield path, methods


# Collect all routes once so we can parametrize cleanly
ROUTES: list[tuple[str, str]] = []
for path, methods in _route_paths():
    if "GET" in methods:
        ROUTES.append((path, "GET"))
    elif "POST" in methods:
        ROUTES.append((path, "POST"))


@pytest.fixture()
def client(monkeypatch):
    """Dev-mode auth (no keys, loopback) so the gate doesn't intercept
    every route with a 401/403."""
    monkeypatch.setattr(auth, "ULTRON_API_KEYS", [])
    return app_module.app.test_client()


@pytest.mark.parametrize("path,method", ROUTES,
                         ids=[f"{m} {p}" for p, m in ROUTES])
def test_route_does_not_crash(client, path, method):
    """Every route must NOT crash with an uncaught exception.

    Acceptable status codes:
      * 2xx -- handler ran and succeeded
      * 3xx -- redirect
      * 4xx -- handler ran and refused (missing field, unauth,
               confirm needed, file not found, validation error)
      * 503 -- handler ran and deliberately reported "this feature is
               not available" (optional module not installed, e.g.
               smart_browser). This is the documented degraded-mode
               response, not a crash.

    Unacceptable:
      * 500 -- uncaught exception in our code (the real bug class
               this smoke test exists to catch)
      * 502 / 504 -- bad gateway / timeout from a sub-process call
                     we made; rare but indicates a code problem
    """
    if method == "GET":
        r = client.get(path)
    else:
        r = client.post(path, json={})
    if r.status_code == 503:
        # Optional-feature degraded mode -- acceptable, not a crash.
        return
    assert r.status_code < 500, (
        f"{method} {path} -> {r.status_code}\n"
        f"body: {r.get_data(as_text=True)[:300]}"
    )


def test_total_route_count_lock():
    """Lock the total route count so we notice when blueprints stop
    registering. The number is informational; bump it intentionally
    when adding new endpoints. ~210 routes was the established baseline
    after Phase 1 wiring; the LEBENX STUDIO blueprint added ~65 more."""
    total = sum(1 for _ in app_module.app.url_map.iter_rules())
    assert 250 <= total <= 320, f"route count drifted: {total}"
