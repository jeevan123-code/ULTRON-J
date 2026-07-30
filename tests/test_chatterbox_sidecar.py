"""HTTP contract of the Chatterbox sidecar.

The sidecar runs under `.venv-chatterbox` (where chatterbox-tts and its
numpy<2 / torch==2.6 pins live). These tests run under Ultron's own venv,
where chatterbox is deliberately NOT installed — so the module must import
without it, and the model load must stay behind a lazy seam.
"""
import json
import threading
from http.client import HTTPConnection

import pytest

import chatterbox_sidecar as cs


@pytest.fixture()
def server():
    """A real sidecar on a real port, with a fake synthesiser injected."""
    calls = []

    def fake_synth(text, reference, exaggeration):
        calls.append({"text": text, "reference": reference,
                      "exaggeration": exaggeration})
        return b"RIFF-FAKE-WAV"

    cs.set_synthesiser(fake_synth)
    httpd = cs.build_server(port=0)          # port 0 = let the OS pick
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port, calls
    httpd.shutdown()
    cs._reset_for_test()


def _post(port, path, payload):
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", path, json.dumps(payload),
                 {"Content-Type": "application/json"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, body


def test_generate_returns_synthesised_audio(server):
    port, calls = server

    status, body = _post(port, "/generate", {
        "text": "Good evening, sir.",
        "reference": "/voices/jarvis.wav",
        "exaggeration": 0.4,
    })

    assert status == 200
    assert body == b"RIFF-FAKE-WAV"
    assert calls == [{"text": "Good evening, sir.",
                      "reference": "/voices/jarvis.wav",
                      "exaggeration": 0.4}]


def test_empty_text_is_rejected_without_loading_the_model(server):
    port, calls = server

    status, _ = _post(port, "/generate", {"text": "   "})

    assert status == 400
    assert calls == []


def test_unknown_path_404s(server):
    port, _ = server
    status, _ = _post(port, "/nope", {"text": "hi"})
    assert status == 404


def test_synth_failure_returns_500_and_keeps_serving(server):
    """One bad generation must not take the sidecar down — Ultron retries."""
    port, calls = server

    def boom(text, reference, exaggeration):
        raise RuntimeError("model exploded")

    cs.set_synthesiser(boom)
    status, _ = _post(port, "/generate", {"text": "hi"})
    assert status == 500

    # still alive and serving
    cs.set_synthesiser(lambda t, r, e: b"RIFF-OK")
    status, body = _post(port, "/generate", {"text": "hi"})
    assert status == 200
    assert body == b"RIFF-OK"


def test_module_imports_without_chatterbox_installed():
    """Ultron's venv has no chatterbox-tts; importing must not explode."""
    assert cs.build_server is not None
