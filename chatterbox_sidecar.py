"""Chatterbox TTS sidecar — cloned-voice synthesis in an isolated process.

Why this exists as a separate process instead of a provider inside
voice_engine.py: chatterbox-tts pins numpy<2, torch==2.6 and transformers==5.2.
Ultron's venv runs numpy 2.4 / torch 2.12 / transformers 5.8 because chromadb
and sentence-transformers need them, and those back the live RAG. Installing
chatterbox alongside would downgrade the stack and break semantic memory.

So chatterbox lives in `.venv-chatterbox` and this script is the only thing
that imports it. Ultron talks to it over localhost HTTP.

Run it (from the repo root):

    .venv-chatterbox/bin/python chatterbox_sidecar.py --port 17580

Then point Ultron at it:

    export ULTRON_TTS_CHATTERBOX=1
    export ULTRON_CHATTERBOX_REF=/home/jeevan/ULTRON_WEB/voices/jarvis.wav

Stdlib-only on purpose — no framework in the dependency path, so the sidecar
venv holds nothing beyond chatterbox itself.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

# Injectable seam. Tests set a fake; production installs the real model
# loader on first use. Keeps this module importable where chatterbox is absent.
_synthesiser: Optional[Callable[[str, str, float], bytes]] = None
_model_lock = threading.Lock()
_model = None

DEFAULT_PORT = 17580


def set_synthesiser(fn: Optional[Callable[[str, str, float], bytes]]) -> None:
    """Install the function that turns (text, reference, exaggeration) -> WAV."""
    global _synthesiser
    _synthesiser = fn


def _reset_for_test() -> None:
    global _synthesiser, _model
    _synthesiser = None
    _model = None


def _load_model():
    """Import and load Chatterbox once. Only ever runs in the sidecar venv."""
    global _model
    with _model_lock:
        if _model is None:
            import torch  # noqa: F401  (imported for side effect / device pick)
            from chatterbox.tts import ChatterboxTTS
            device = "cuda" if _cuda_available() else "cpu"
            print(f"[chatterbox] loading model on {device} (first call is slow)…",
                  flush=True)
            _model = ChatterboxTTS.from_pretrained(device=device)
            print("[chatterbox] model ready", flush=True)
    return _model


def _cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _real_synthesise(text: str, reference: str, exaggeration: float) -> bytes:
    """Generate WAV bytes in the cloned voice."""
    import io
    import torchaudio
    model = _load_model()
    kwargs = {"exaggeration": exaggeration}
    # A reference clip is what makes it a *cloned* voice; without one
    # Chatterbox falls back to its own default speaker.
    if reference and os.path.exists(reference):
        kwargs["audio_prompt_path"] = reference
    wav = model.generate(text, **kwargs)
    buf = io.BytesIO()
    torchaudio.save(buf, wav, model.sr, format="wav")
    return buf.getvalue()


def _synthesise(text: str, reference: str, exaggeration: float) -> bytes:
    fn = _synthesiser or _real_synthesise
    return fn(text, reference, exaggeration)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def do_POST(self) -> None:  # noqa: N802  (stdlib naming)
        if self.path.rstrip("/") != "/generate":
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._send_json(400, {"error": "invalid JSON body"})
            return

        text = (payload.get("text") or "").strip()
        if not text:
            self._send_json(400, {"error": "text is required"})
            return

        try:
            audio = _synthesise(
                text,
                payload.get("reference") or "",
                float(payload.get("exaggeration", 0.5)),
            )
        except Exception as e:
            # Never die on one bad generation — Ultron falls back to edge and
            # the next request should still find us listening.
            print(f"[chatterbox] synthesis failed: {e}", flush=True)
            self._send_json(500, {"error": str(e)})
            return

        self._send(200, audio, "audio/wav")

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/health", ""):
            self._send_json(200, {"ok": True, "model_loaded": _model is not None})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # quieter than the stdlib default
        return


def build_server(port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
    """Build (but do not start) the sidecar server. port=0 picks a free port."""
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> None:
    ap = argparse.ArgumentParser(description="Chatterbox TTS sidecar")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--preload", action="store_true",
                    help="load the model at startup instead of on first request")
    args = ap.parse_args()

    if args.preload:
        _load_model()

    httpd = build_server(port=args.port, host=args.host)
    print(f"[chatterbox] sidecar listening on http://{args.host}:{args.port}",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[chatterbox] shutting down", flush=True)
        httpd.shutdown()


if __name__ == "__main__":
    main()
