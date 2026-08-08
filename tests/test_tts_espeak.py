"""espeak-ng — absolute last-resort offline TTS fallback.

Fires only when every other provider (including edge) has failed, e.g. no
network. Zero API key, zero model download — just the system espeak-ng
CLI, if installed. See docs/plans/2026-08-02-tts-provider-expansion-design.md.
"""
from unittest.mock import MagicMock
import pytest

import voice_engine as ve


@pytest.fixture(autouse=True)
def _no_cache_deterministic_chain(monkeypatch):
    monkeypatch.setattr(ve, "_get_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_set_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "PIPER_AVAILABLE", False)
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", False)
    monkeypatch.setattr(ve, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(ve, "OPENAI_API_KEY", "")
    monkeypatch.delenv("ULTRON_TTS_CHATTERBOX", raising=False)


def test_espeak_not_attempted_when_edge_succeeds(monkeypatch):
    """espeak is a last resort — a healthy edge must win first."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")
    called = []
    monkeypatch.setattr(
        ve, "_tts_espeak", lambda t, m: called.append(t) or b"ESPEAK")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "edge"
    assert audio == b"EDGE"
    assert called == []


def test_espeak_used_when_everything_else_fails(monkeypatch):
    """The never-silent guarantee: edge down + no local models -> espeak."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)

    def _edge_down(t, m):
        raise RuntimeError("no network")

    monkeypatch.setattr(ve, "_tts_edge", _edge_down)
    monkeypatch.setattr(ve, "_tts_espeak", lambda t, m: b"ESPEAK")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "espeak"
    assert audio == b"ESPEAK"


def test_espeak_absent_from_chain_when_binary_not_installed(monkeypatch):
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", False)

    def _edge_down(t, m):
        raise RuntimeError("no network")

    monkeypatch.setattr(ve, "_tts_edge", _edge_down)
    called = []
    monkeypatch.setattr(
        ve, "_tts_espeak", lambda t, m: called.append(t) or b"ESPEAK")

    with pytest.raises(RuntimeError, match="All TTS providers failed"):
        ve.tts("hello", provider="auto")

    assert called == []


def test_espeak_appended_after_edge_for_explicit_provider_override(monkeypatch):
    """provider='piper' with piper failing must still fall through edge -> espeak."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)

    def _piper_down(t, m):
        raise RuntimeError("piper not installed")

    def _edge_down(t, m):
        raise RuntimeError("no network")

    monkeypatch.setattr(ve, "_tts_piper", _piper_down)
    monkeypatch.setattr(ve, "_tts_edge", _edge_down)
    monkeypatch.setattr(ve, "_tts_espeak", lambda t, m: b"ESPEAK")

    audio, provider = ve.tts("hello", provider="piper")

    assert provider == "espeak"
    assert audio == b"ESPEAK"


def test_tts_espeak_invokes_cli_and_returns_wav_bytes(monkeypatch):
    """Real subprocess contract: espeak-ng writes a WAV via -w, we read it back."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)

    def _fake_run(cmd, check, capture_output, timeout):
        wav_path = cmd[cmd.index("-w") + 1]
        with open(wav_path, "wb") as f:
            f.write(b"RIFF....WAVEfmt fake-espeak-audio")
        return MagicMock(returncode=0)

    monkeypatch.setattr(ve.subprocess, "run", _fake_run)

    audio = ve._tts_espeak("Hello there.", "FOCUSED")

    assert audio.startswith(b"RIFF")


def test_tts_espeak_uses_list_form_argv_no_shell(monkeypatch):
    """Hardening convention (2026-07-03/07-26 fixes): never shell=True."""
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", True)
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        wav_path = cmd[cmd.index("-w") + 1]
        with open(wav_path, "wb") as f:
            f.write(b"RIFF")
        return MagicMock(returncode=0)

    monkeypatch.setattr(ve.subprocess, "run", _fake_run)

    ve._tts_espeak("hi", "FOCUSED")

    assert isinstance(captured["cmd"], list)
    assert captured["kwargs"].get("shell", False) is False


def test_tts_espeak_raises_when_binary_missing(monkeypatch):
    monkeypatch.setattr(ve, "ESPEAK_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="espeak-ng not installed"):
        ve._tts_espeak("hi", "FOCUSED")
