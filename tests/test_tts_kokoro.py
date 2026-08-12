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


def test_kokoro_selected_when_available_and_nothing_ahead_of_it(monkeypatch, tmp_path):
    """With piper/elevenlabs/openai off, kokoro must win over edge.

    Paths are pointed at real (empty) tmp files rather than relying on this
    machine's actual downloaded model files, so the test is hermetic and
    would still pass on a fresh clone / CI box that lacks them.
    """
    onnx_path = tmp_path / "kokoro-v1.0.onnx"
    voices_path = tmp_path / "voices-v1.0.bin"
    onnx_path.write_bytes(b"")
    voices_path.write_bytes(b"")
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", True)
    monkeypatch.setattr(ve, "_KOKORO_ONNX_PATH", str(onnx_path))
    monkeypatch.setattr(ve, "_KOKORO_VOICES_PATH", str(voices_path))
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


def test_kokoro_absent_from_chain_when_model_files_missing_on_fresh_clone(
    monkeypatch, tmp_path
):
    """kokoro-onnx installed (KOKORO_AVAILABLE=True) but the 2 large model
    files not yet downloaded (they're .gitignore'd, so every fresh clone
    starts without them) must NOT attempt kokoro and fail every call —
    it must fall straight through to edge, mirroring piper's existing
    os.path.exists guard."""
    missing_onnx = tmp_path / "kokoro-v1.0.onnx"
    missing_voices = tmp_path / "voices-v1.0.bin"
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", True)
    monkeypatch.setattr(ve, "_KOKORO_ONNX_PATH", str(missing_onnx))
    monkeypatch.setattr(ve, "_KOKORO_VOICES_PATH", str(missing_voices))
    called = []
    monkeypatch.setattr(
        ve, "_tts_kokoro", lambda t, m: called.append(t) or b"KOKORO")
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "edge"
    assert called == []
