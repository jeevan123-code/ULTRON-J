"""Chatterbox TTS provider — cloned-voice output via an isolated local sidecar.

Chatterbox pins numpy<2 / torch==2.6 / transformers==5.2, which would drag
Ultron's own venv backwards and break chromadb + sentence-transformers (the
live RAG). So it never runs in-process: it lives in `.venv-chatterbox` behind
a small HTTP sidecar, and this provider only speaks to it over localhost.

Default OFF — `edge` stays the fast path unless ULTRON_TTS_CHATTERBOX=1.
"""
from unittest.mock import patch, MagicMock
import pytest

import voice_engine as ve


@pytest.fixture(autouse=True)
def _no_cache_deterministic_chain(monkeypatch):
    """Bypass the TTS cache and pin every other backend off, so the chain the
    test observes is the chain the code actually built."""
    monkeypatch.setattr(ve, "_get_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_set_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "PIPER_AVAILABLE", False)
    monkeypatch.setattr(ve, "KOKORO_AVAILABLE", False)
    monkeypatch.setattr(ve, "ELEVENLABS_API_KEY", "")
    monkeypatch.setattr(ve, "OPENAI_API_KEY", "")
    monkeypatch.delenv("ULTRON_TTS_CHATTERBOX", raising=False)


def test_chatterbox_absent_from_auto_chain_when_flag_off(monkeypatch):
    """Default-OFF: a normal reply must not pay the cloned-voice latency."""
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")
    called = []
    monkeypatch.setattr(
        ve, "_tts_chatterbox", lambda t, m: called.append(t) or b"CB")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "edge"
    assert audio == b"EDGE"
    assert called == []


def test_chatterbox_leads_auto_chain_when_enabled(monkeypatch):
    """Enabled means preferred — the whole point is to hear the cloned voice."""
    monkeypatch.setenv("ULTRON_TTS_CHATTERBOX", "1")
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")
    monkeypatch.setattr(ve, "_tts_chatterbox", lambda t, m: b"CB")

    audio, provider = ve.tts("hello", provider="auto")

    assert provider == "chatterbox"
    assert audio == b"CB"


def test_tts_chatterbox_posts_text_to_sidecar_and_returns_audio(monkeypatch):
    """The provider is a thin client: text in, audio bytes out."""
    monkeypatch.setenv("ULTRON_CHATTERBOX_URL", "http://127.0.0.1:17580")
    monkeypatch.setenv("ULTRON_CHATTERBOX_REF", "/voices/jarvis.wav")

    resp = MagicMock(status_code=200, content=b"ID3-CLONED-AUDIO")
    resp.raise_for_status = MagicMock()

    with patch.object(ve.requests, "post", return_value=resp) as post:
        audio = ve._tts_chatterbox("Good evening, sir.", "FOCUSED")

    assert audio == b"ID3-CLONED-AUDIO"
    sent = post.call_args
    assert sent.args[0].startswith("http://127.0.0.1:17580")
    assert sent.kwargs["json"]["text"] == "Good evening, sir."
    assert sent.kwargs["json"]["reference"] == "/voices/jarvis.wav"


def test_sidecar_down_falls_through_to_edge(monkeypatch):
    """The sidecar is optional infrastructure. If it is not running, Ultron
    must still speak rather than going silent."""
    monkeypatch.setenv("ULTRON_TTS_CHATTERBOX", "1")

    attempted = []

    def _refused(*a, **k):
        attempted.append(a)
        raise OSError("connection refused")

    monkeypatch.setattr(ve.requests, "post", _refused)
    monkeypatch.setattr(ve, "_tts_edge", lambda t, m: b"EDGE")

    audio, provider = ve.tts("hello", provider="auto")

    # It must have genuinely tried the sidecar, then recovered — not merely
    # skipped chatterbox and gone straight to edge.
    assert attempted, "chatterbox sidecar was never contacted"
    assert provider == "edge"
    assert audio == b"EDGE"
