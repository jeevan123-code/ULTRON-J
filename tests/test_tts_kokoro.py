"""Kokoro TTS provider — local, offline, no API key required.

Restores the auto chain's second local option (after piper) now that
kokoro-onnx + the onnx/voices model files are installed. See
docs/plans/2026-08-02-tts-provider-expansion-design.md.
"""
import pytest

import voice_engine as ve


@pytest.fixture(autouse=True)
def _no_cache_deterministic_chain(monkeypatch):
    """Bypass the TTS cache and pin every other backend off, so the chain
    the test observes is the chain the code actually built."""
    monkeypatch.setattr(ve, "_get_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_set_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "PIPER_AVAILABLE", False)
    monkeypatch.setattr(ve, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(ve, "OPENAI_API_KEY", "")
    monkeypatch.delenv("ULTRON_TTS_CHATTERBOX", raising=False)


def test_kokoro_selected_when_available_and_nothing_ahead_of_it(monkeypatch):
    """With piper/elevenlabs/openai off, kokoro must win over edge."""
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", True)
    monkeypatch.setattr(ve, "_tts_kokoro", lambda t, m: b"KOKORO")
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "kokoro"
    assert audio == b"KOKORO"


def test_kokoro_absent_from_chain_when_not_installed(monkeypatch):
    """If kokoro-onnx / model files are missing, must not be attempted."""
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", False)
    called = []
    monkeypatch.setattr(
        ve, "_tts_kokoro", lambda t, m: called.append(t) or b"KOKORO")
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "edge"
    assert called == []
