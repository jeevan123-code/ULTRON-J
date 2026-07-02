"""Integration tests for the Phase 5b live wiring.

Phase 5b's pipeline logic already has 60 tests; these cover the GLUE that was
previously missing — the hooks in voice_engine.parse_voice_command and
voice_routes that actually invoke that pipeline. Both hooks are flag-gated
(ULTRON_PHASE5B_ENABLED) and default OFF.
"""
import os

import pytest


# ── voice_engine hook: pending stranger -> confirm_stranger, consumes text ──
def test_parse_voice_command_routes_pending_stranger(monkeypatch):
    import voice_engine
    import stranger_offer

    monkeypatch.setenv("ULTRON_PHASE5B_ENABLED", "1")
    monkeypatch.setattr(stranger_offer, "peek_pending", lambda: {"embedding": []})
    captured = {}

    def _fake_confirm(reply):
        captured["reply"] = reply
        return {"enrolled": True, "name": "Ravi"}

    monkeypatch.setattr(stranger_offer, "confirm_stranger", _fake_confirm)

    out = voice_engine.parse_voice_command("that's Ravi, my brother")
    assert out is None                      # utterance consumed by enrollment
    assert captured.get("reply") == "that's Ravi, my brother"


def test_parse_voice_command_ignores_stranger_when_flag_off(monkeypatch):
    import voice_engine
    import stranger_offer

    monkeypatch.setenv("ULTRON_PHASE5B_ENABLED", "0")
    called = {"n": 0}
    monkeypatch.setattr(stranger_offer, "peek_pending",
                        lambda: called.__setitem__("n", called["n"] + 1))
    # With the flag off the 5b block must not even query stranger_offer.
    voice_engine.parse_voice_command("hello there")
    assert called["n"] == 0


# ── voice_routes hook: _maybe_voice_id writes a temp clip + runs pipeline ──
def test_maybe_voice_id_runs_pipeline_when_enabled(monkeypatch):
    import voice_routes
    import voice_id_pipeline

    monkeypatch.setenv("ULTRON_PHASE5B_ENABLED", "1")
    seen = {}

    def _fake_process(path):
        seen["path"] = path
        seen["existed_during_call"] = os.path.exists(path)
        return {"action": "recorded"}

    monkeypatch.setattr(voice_id_pipeline, "process_audio_clip", _fake_process)

    voice_routes._maybe_voice_id(b"RIFFfakeaudio")
    assert seen.get("existed_during_call") is True      # path valid at call time
    assert not os.path.exists(seen["path"])             # cleaned up afterward


def test_maybe_voice_id_noop_when_disabled(monkeypatch):
    import voice_routes
    import voice_id_pipeline

    monkeypatch.setenv("ULTRON_PHASE5B_ENABLED", "0")
    called = {"n": 0}
    monkeypatch.setattr(voice_id_pipeline, "process_audio_clip",
                        lambda p: called.__setitem__("n", called["n"] + 1))
    voice_routes._maybe_voice_id(b"data")
    voice_routes._maybe_voice_id(b"")     # also no-op on empty
    assert called["n"] == 0
