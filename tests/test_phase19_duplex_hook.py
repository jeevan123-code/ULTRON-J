"""Phase 19 wiring — the duplex state machine gets a per-session home + routes.

duplex_voice is a PURE controller: it decides, a driver acts. It shipped with
neither, so nothing ever created a controller. This hook holds one per voice
session and exposes it over the voice blueprint, which is the surface the
browser client can drive.

The audio DRIVER (real barge-in on live PCM) stays the hardware seam — that is
honest, and unchanged here. What is fixed is that the decision logic is now
reachable from production instead of only from its own test file.
"""
import flask
import pytest

import phase19_duplex_hook as hook
import voice_routes
from duplex_voice import ACT_START_LISTEN, ACT_STOP_TTS, State


@pytest.fixture(autouse=True)
def _isolate():
    hook._reset_for_test()
    yield
    hook._reset_for_test()


@pytest.fixture
def client():
    app = flask.Flask(__name__)
    app.register_blueprint(voice_routes.voice_bp)
    return app.test_client()


# ── per-session controllers ─────────────────────────────────────────────────
def test_controller_is_created_per_session():
    a = hook.controller_for("s1")
    b = hook.controller_for("s2")
    assert a is not b
    assert hook.controller_for("s1") is a, "same session must reuse its controller"


def test_wake_starts_listening():
    r = hook.handle("s1", "wake")
    assert r["actions"] == [ACT_START_LISTEN]
    assert r["state"] == State.LISTENING.value
    assert r["conversation_active"] is True


def test_barge_in_stops_tts_and_listens():
    hook.handle("s1", "wake")
    hook.handle("s1", "speech_final", text="hello")
    hook.handle("s1", "response_ready")
    r = hook.handle("s1", "user_interrupt")
    assert ACT_STOP_TTS in r["actions"]
    assert ACT_START_LISTEN in r["actions"]


def test_follow_up_needs_no_wake_word():
    hook.handle("s1", "wake")
    hook.handle("s1", "speech_final", text="hi")
    hook.handle("s1", "response_ready")
    r = hook.handle("s1", "tts_finished")
    assert r["actions"] == [ACT_START_LISTEN]
    assert r["state"] == State.LISTENING.value


def test_silence_closes_the_conversation():
    hook.handle("s1", "wake")
    r = hook.handle("s1", "silence")
    assert r["state"] == State.IDLE.value
    assert r["conversation_active"] is False


def test_unknown_event_is_rejected_not_crashed():
    r = hook.handle("s1", "nonsense")
    assert r["ok"] is False
    assert "unknown event" in r["error"].lower()


def test_session_table_is_bounded():
    for i in range(hook.MAX_SESSIONS + 25):
        hook.controller_for(f"s{i}")
    assert len(hook._controllers) <= hook.MAX_SESSIONS


def test_reset_clears_one_session():
    hook.handle("s1", "wake")
    hook.reset("s1")
    assert hook.controller_for("s1").state == State.IDLE


# ── HTTP surface ────────────────────────────────────────────────────────────
def test_state_route_reports_snapshot(client):
    r = client.get("/api/voice/duplex/state?session_id=s1")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["state"] == State.IDLE.value


def test_event_route_drives_the_machine(client):
    r = client.post("/api/voice/duplex/event",
                    json={"session_id": "s1", "event": "wake"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["actions"] == [ACT_START_LISTEN]


def test_event_route_rejects_unknown_event(client):
    r = client.post("/api/voice/duplex/event",
                    json={"session_id": "s1", "event": "banana"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_event_route_requires_an_event(client):
    r = client.post("/api/voice/duplex/event", json={"session_id": "s1"})
    assert r.status_code == 400
