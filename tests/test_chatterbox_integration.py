"""The seam: voice_engine's provider talking to the real sidecar over HTTP.

Both halves are unit-tested separately, but they are developed against a
contract written twice — once in the client, once in the handler. This test
runs a genuine ThreadingHTTPServer and a genuine requests.post between them,
so a drift in path, field names or content handling fails here.

The synthesiser is faked (chatterbox itself is not installed in this venv, by
design) — everything else is real.
"""
import threading

import pytest

import chatterbox_sidecar as cs
import voice_engine as ve


@pytest.fixture()
def live_sidecar(monkeypatch):
    received = {}

    def fake_synth(text, reference, exaggeration):
        received.update(text=text, reference=reference,
                        exaggeration=exaggeration)
        return b"RIFF....WAVEfmt cloned-audio"

    cs.set_synthesiser(fake_synth)
    httpd = cs.build_server(port=0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    monkeypatch.setenv("ULTRON_CHATTERBOX_URL", f"http://127.0.0.1:{port}")
    yield received
    httpd.shutdown()
    cs._reset_for_test()


def test_provider_reaches_sidecar_and_gets_audio_back(live_sidecar, monkeypatch):
    monkeypatch.setenv("ULTRON_CHATTERBOX_REF", "/voices/jarvis.wav")

    audio = ve._tts_chatterbox("Good evening, sir.", "FOCUSED")

    assert audio == b"RIFF....WAVEfmt cloned-audio"
    assert live_sidecar["text"] == "Good evening, sir."
    assert live_sidecar["reference"] == "/voices/jarvis.wav"
    # FOCUSED maps to a calmer delivery than the 0.5 default
    assert live_sidecar["exaggeration"] == pytest.approx(0.4)


def test_full_tts_chain_uses_sidecar_when_enabled(live_sidecar, monkeypatch):
    """End to end through the public tts() entry point, not the private one."""
    monkeypatch.setenv("ULTRON_TTS_CHATTERBOX", "1")
    monkeypatch.setattr(ve, "_get_cached", lambda *a, **k: None)
    monkeypatch.setattr(ve, "_set_cached", lambda *a, **k: None)

    audio, provider = ve.tts("Systems nominal.", provider="auto")

    assert provider == "chatterbox"
    assert audio == b"RIFF....WAVEfmt cloned-audio"
    assert live_sidecar["text"] == "Systems nominal."
