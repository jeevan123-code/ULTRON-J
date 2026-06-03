"""
Phase 1 acceptance suite. Proves the four properties from the plan:

  (a) No keys configured + non-loopback caller     -> 403
  (b) Keys configured + missing/wrong X-API-Key    -> 401
      Keys configured + correct X-API-Key          -> request proceeds
      Keys configured + correct ?api_key=          -> request proceeds
  (c) /self_upgrade/run + the four /self_modify/*
      write endpoints without confirm token        -> 428
      same endpoints WITH the right confirm token  -> proceeds
  (d) /phone/tap, /phone/key, /phone/volume reject
      non-integer / out-of-range / unknown values  -> 400

Run:  venv/bin/python -m pytest tests/test_auth.py -v
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module                                # noqa: E402
import auth                                              # noqa: E402


@pytest.fixture()
def client():
    """Flask test client. Each test gets a fresh client so monkey-patches
    on auth.ULTRON_API_KEYS don't leak between tests."""
    return app_module.app.test_client()


@pytest.fixture()
def no_keys(monkeypatch):
    """Force dev-mode (no keys) for the auth gate."""
    monkeypatch.setattr(auth, "ULTRON_API_KEYS", [])


@pytest.fixture()
def with_keys(monkeypatch):
    """Configure a known API key. Returns the key string."""
    key = "phase1-test-key"
    monkeypatch.setattr(auth, "ULTRON_API_KEYS", [key])
    return key


# ─── (a) No keys, remote caller -> 403 ────────────────────────────────────────

def test_remote_call_without_keys_is_403(client, no_keys):
    r = client.get(
        "/provider_health",
        environ_overrides={"REMOTE_ADDR": "192.168.1.99"},
    )
    assert r.status_code == 403
    body = r.get_json()
    assert "no API keys set" in body["error"]
    assert "ULTRON_API_KEYS" in body["hint"]


def test_loopback_call_without_keys_passes(client, no_keys):
    """Dev convenience: 127.0.0.1 still works when no keys are set."""
    r = client.get("/provider_health")  # test_client defaults to 127.0.0.1
    # Not asserting 200 — the underlying handler may legitimately 500 if
    # an external service is down. We're testing the GATE, not the handler.
    assert r.status_code != 403, "loopback should not be blocked in dev mode"


# ─── (b) Keys configured, wrong/missing/correct API key ───────────────────────

def test_keys_set_missing_header_is_401(client, with_keys):
    r = client.get("/provider_health")
    assert r.status_code == 401
    assert r.get_json()["error"] == "unauthorized"


def test_keys_set_wrong_header_is_401(client, with_keys):
    r = client.get("/provider_health", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401


def test_keys_set_correct_header_passes(client, with_keys):
    r = client.get("/provider_health", headers={"X-API-Key": with_keys})
    assert r.status_code != 401, "correct X-API-Key must pass the auth gate"


def test_keys_set_correct_query_param_passes(client, with_keys):
    r = client.get(f"/provider_health?api_key={with_keys}")
    assert r.status_code != 401, "correct ?api_key= must pass the auth gate"


# ─── Public-path / preflight bypass ───────────────────────────────────────────

def test_public_health_path_bypasses_auth(client, with_keys):
    """/health is in PUBLIC_PATHS — must pass even with no API key sent."""
    r = client.get("/health")
    assert r.status_code == 200


def test_options_preflight_bypasses_auth(client, with_keys):
    """CORS preflight (OPTIONS) must not be gated."""
    r = client.options("/provider_health")
    # 404 is fine (no OPTIONS handler registered for that route); the
    # important thing is that the gate did NOT respond 401.
    assert r.status_code != 401, "OPTIONS preflight must bypass the gate"


# ─── (c) Confirm-token gate on dangerous endpoints ────────────────────────────

DANGEROUS = [
    ("/self_upgrade/run",       "self_upgrade_run"),
    ("/self_modify/improve",    "self_modify_improve"),
    ("/self_modify/patch",      "self_modify_patch"),
    ("/self_modify/rollback",   "self_modify_rollback"),
    # The /<proposal_id> variants take a path arg; test below.
]


@pytest.mark.parametrize("path,action_name", DANGEROUS,
                         ids=[p[0] for p in DANGEROUS])
def test_dangerous_route_without_confirm_is_428(client, no_keys, path, action_name):
    r = client.post(path, json={})
    assert r.status_code == 428, f"{path} should require confirm token"
    body = r.get_json()
    assert body["error"] == "confirm token required"
    assert body["action"] == action_name
    assert body["required_value"] == f"I CONFIRM {action_name}"


def test_self_modify_apply_proposal_requires_confirm(client, no_keys):
    r = client.post("/self_modify/apply/some-proposal-id", json={})
    assert r.status_code == 428
    assert r.get_json()["action"] == "self_modify_apply"


def test_self_modify_rollback_proposal_requires_confirm(client, no_keys):
    r = client.post("/self_modify/rollback/some-proposal-id", json={})
    assert r.status_code == 428
    assert r.get_json()["action"] == "self_modify_rollback"


def test_self_upgrade_with_confirm_passes_gate(client, no_keys):
    """The gate must NOT return 428 when the right confirm is provided.
    The handler underneath may succeed or fail for unrelated reasons —
    we only care that the gate let it through."""
    r = client.post(
        "/self_upgrade/run",
        json={"confirm": "I CONFIRM self_upgrade_run"},
    )
    assert r.status_code != 428, "right confirm token must pass the gate"


def test_self_upgrade_wrong_confirm_still_rejected(client, no_keys):
    """A near-miss confirm value (right field, wrong content) must still
    be rejected — that's the whole point of an echoed token."""
    r = client.post("/self_upgrade/run", json={"confirm": "yes"})
    assert r.status_code == 428


# ─── (d) Phone-input validation ───────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"x": "foo", "y": 100},
    {"x": -1, "y": 100},
    {"x": 99999, "y": 100},
    {"x": 100, "y": None},
    {},                          # missing both
], ids=["x_string", "x_negative", "x_too_big", "y_none", "missing"])
def test_phone_tap_rejects_bad_coords(client, no_keys, body):
    r = client.post("/phone/tap", json=body)
    assert r.status_code == 400, f"phone/tap should 400 on {body!r}"
    assert "x,y must be integers in [0,4096]" in r.get_json()["error"]


def test_phone_tap_accepts_valid_coords(client, no_keys):
    """Valid coords pass the gate. Underlying handler may say 'phone not
    connected' but it must not 400."""
    r = client.post("/phone/tap", json={"x": 500, "y": 900})
    assert r.status_code != 400


def test_phone_tap_coerces_floats(client, no_keys):
    """A float coord (100.5) is acceptable input — int() truncates to 100,
    which is within range. Documented behavior, not a bug."""
    r = client.post("/phone/tap", json={"x": 100.7, "y": 200.3})
    assert r.status_code != 400


@pytest.mark.parametrize("body", [
    {"keycode": "HOME"},
    {"keycode": -5},
    {"keycode": 99999},
    {},
], ids=["string", "negative", "too_big", "missing"])
def test_phone_key_rejects_bad_keycode(client, no_keys, body):
    r = client.post("/phone/key", json=body)
    assert r.status_code == 400
    assert "keycode must be an integer in [0,300]" in r.get_json()["error"]


@pytest.mark.parametrize("action", ["maximum", "loud", "off", "", "UP\nbash"],
                         ids=["maximum", "loud", "off", "empty", "injection"])
def test_phone_volume_rejects_bad_action(client, no_keys, action):
    r = client.post("/phone/volume", json={"action": action})
    assert r.status_code == 400
    assert "action must be one of" in r.get_json()["error"]


def test_phone_volume_accepts_valid_actions(client, no_keys):
    for action in ("up", "down", "mute"):
        r = client.post("/phone/volume", json={"action": action})
        assert r.status_code != 400, f"action={action!r} should pass validation"
