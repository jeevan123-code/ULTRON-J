"""
studio/providers/voice.py — Voiceover adapters.

Two adapters:

  EdgeTTSProvider        No credentials. `edge-tts` is already a project
                         dependency, so the audio half of the pipeline works
                         out of the box — this is what makes the voice timing
                         engine testable without anyone buying a TTS plan.
  ElevenLabsProvider     ELEVENLABS_API_KEY. Higher quality, real voice
                         catalogue, per-character billing.

Both are synchronous: TTS returns audio in seconds, so `generate_speech()`
blocks and returns a terminal `GenerationStatus` carrying the bytes. The job
worker runs it on a worker thread, so the web server is never blocked.

Duration is *measured*, never assumed. `measure_duration()` reads the real
length of the returned audio, because the voice timing engine's entire job is
to reconcile planned scene lengths against what the narration actually takes.
A guessed duration would silently corrupt the timeline — precisely the
failure mode the spec calls out.
"""

from __future__ import annotations

import asyncio
import io
import os
import struct
import subprocess
import tempfile
from typing import Optional

from . import http
from .base import (
    Capabilities, CostEstimate, GenerationStatus, JobState, ProviderError,
    Voice, VoiceGenerationProvider,
)

try:
    from config import ELEVENLABS_API_KEY
except ImportError:  # pragma: no cover
    ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip() or None


# =============================================================================
# DURATION MEASUREMENT
# =============================================================================

def measure_duration(data: bytes, mime: str = "") -> Optional[float]:
    """Measure real audio duration in seconds, or return None.

    Three strategies, most reliable first. Returning None is a valid,
    honest answer — callers must handle "unknown duration" rather than
    receive a fabricated number.
    """
    # 1. ffprobe — authoritative for every format, when it is installed.
    duration = _duration_via_ffprobe(data)
    if duration is not None:
        return duration

    # 2. WAV header arithmetic — exact, no dependencies.
    if data[:4] == b"RIFF":
        duration = _duration_via_wav_header(data)
        if duration is not None:
            return duration

    # 3. mutagen, if the environment happens to have it.
    try:
        from mutagen import File as MutagenFile  # type: ignore

        parsed = MutagenFile(io.BytesIO(data))
        if parsed is not None and getattr(parsed, "info", None):
            length = getattr(parsed.info, "length", None)
            if length:
                return float(length)
    except Exception:  # noqa: BLE001 - optional dependency
        pass

    return None


def _duration_via_ffprobe(data: bytes) -> Optional[float]:
    if not _which("ffprobe"):
        return None
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".audio") as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", tmp_path],
            capture_output=True, text=True, timeout=30, check=False,
        )
        value = (out.stdout or "").strip()
        return float(value) if value else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _duration_via_wav_header(data: bytes) -> Optional[float]:
    """Parse fmt/data chunks. Exact for PCM WAV."""
    try:
        pos, byte_rate, data_size = 12, 0, 0
        while pos + 8 <= len(data):
            chunk_id = data[pos:pos + 4]
            chunk_size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
            if chunk_id == b"fmt " and pos + 16 <= len(data):
                byte_rate = struct.unpack("<I", data[pos + 16:pos + 20])[0]
            elif chunk_id == b"data":
                data_size = chunk_size
                break
            pos += 8 + chunk_size + (chunk_size % 2)
        if byte_rate and data_size:
            return round(data_size / byte_rate, 3)
    except Exception:  # noqa: BLE001
        return None
    return None


def _which(binary: str) -> Optional[str]:
    from shutil import which
    return which(binary)


# =============================================================================
# EDGE TTS (no credentials)
# =============================================================================

class EdgeTTSProvider(VoiceGenerationProvider):
    """Microsoft Edge read-aloud voices via the `edge-tts` package.

    Free and keyless, which makes it the default so that Studio Phase 4 is
    genuinely exercisable. It is a consumer endpoint with no SLA — stated in
    `capabilities().notes` so the UI can say so rather than imply otherwise.
    """

    name = "edge_tts"
    label = "Edge TTS (free, no key)"
    credential_env = ()
    docs_url = "https://github.com/rany2/edge-tts"

    DEFAULT_VOICE = "en-US-AriaNeural"

    # A small curated set for the picker; `list_voices()` queries the real
    # catalogue when the package can reach the service.
    FALLBACK_VOICES = [
        ("en-US-AriaNeural", "Aria (US, female)", "en-US", "female"),
        ("en-US-GuyNeural", "Guy (US, male)", "en-US", "male"),
        ("en-GB-SoniaNeural", "Sonia (UK, female)", "en-GB", "female"),
        ("en-GB-RyanNeural", "Ryan (UK, male)", "en-GB", "male"),
        ("en-IN-NeerjaNeural", "Neerja (India, female)", "en-IN", "female"),
        ("en-IN-PrabhatNeural", "Prabhat (India, male)", "en-IN", "male"),
        ("en-AU-NatashaNeural", "Natasha (AU, female)", "en-AU", "female"),
    ]

    def is_installed(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False

    def is_connected(self) -> bool:
        return self.is_installed()

    def capabilities(self) -> Capabilities:
        return Capabilities(
            models=["edge-neural"],
            languages=["en", "hi", "te", "es", "fr", "de", "ja", "zh"],
            max_variations=1,
            cancellation=False,
            reports_progress=False,
            cost_estimation=True,
            notes="Free consumer endpoint with no SLA. Supports rate and "
                  "pitch adjustment; no emotional-tone control.",
        )

    def verify_connection(self) -> dict:
        if not self.is_installed():
            return {"ok": False, "verified": False,
                    "error": "edge-tts package not installed"}
        try:
            voices = self._fetch_voice_catalogue()
            return {"ok": True, "verified": True, "voices_seen": len(voices)}
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            return {"ok": False, "verified": False, "error": str(exc)}

    def estimate_cost(self, request=None) -> CostEstimate:
        return CostEstimate(amount=0.0, confidence="published",
                            basis="free endpoint, no billing")

    def _fetch_voice_catalogue(self) -> list[dict]:
        import edge_tts

        async def _list():
            return await edge_tts.list_voices()

        return _run_async(_list())

    def list_voices(self, language: str = "") -> list[Voice]:
        if not self.is_installed():
            return []
        try:
            catalogue = self._fetch_voice_catalogue()
            voices = [
                Voice(
                    id=v.get("ShortName", ""),
                    name=v.get("FriendlyName") or v.get("ShortName", ""),
                    language=v.get("Locale", ""),
                    gender=(v.get("Gender") or "").lower(),
                    provider=self.name,
                )
                for v in catalogue if v.get("ShortName")
            ]
        except Exception:  # noqa: BLE001 - fall back to the curated list
            voices = [
                Voice(id=vid, name=name, language=locale, gender=gender,
                      provider=self.name)
                for vid, name, locale, gender in self.FALLBACK_VOICES
            ]

        if language:
            prefix = language.lower()
            voices = [v for v in voices if v.language.lower().startswith(prefix)]
        return voices

    def generate_speech(self, text: str, voice_id: str = "", *,
                        language: str = "en", speed: float = 1.0,
                        **extra) -> GenerationStatus:
        if not self.is_installed():
            return GenerationStatus(state=JobState.FAILED,
                                    error="edge-tts package not installed")
        if not (text or "").strip():
            return GenerationStatus(state=JobState.FAILED,
                                    error="no text to synthesise")

        import edge_tts

        voice = voice_id or self.DEFAULT_VOICE
        # edge-tts takes a percentage delta, not a multiplier.
        rate = f"{int(round((speed - 1.0) * 100)):+d}%"
        kwargs = {"rate": rate}
        if extra.get("pitch_hz"):
            kwargs["pitch"] = f"{int(extra['pitch_hz']):+d}Hz"

        async def _synth() -> bytes:
            communicate = edge_tts.Communicate(text, voice, **kwargs)
            buf = bytearray()
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    buf.extend(chunk["data"])
            return bytes(buf)

        try:
            audio = _run_async(_synth())
        except Exception as exc:  # noqa: BLE001
            return GenerationStatus(state=JobState.FAILED,
                                    error=f"edge-tts synthesis failed: {exc}")

        if not audio:
            return GenerationStatus(state=JobState.FAILED,
                                    error="edge-tts returned no audio")

        return GenerationStatus(
            state=JobState.COMPLETED, output_bytes=audio, mime="audio/mpeg",
            duration_s=measure_duration(audio, "audio/mpeg"),
            actual_cost=0.0, stage="completed",
        )


# =============================================================================
# ELEVENLABS
# =============================================================================

class ElevenLabsProvider(VoiceGenerationProvider):
    name = "elevenlabs"
    label = "ElevenLabs"
    credential_env = ("ELEVENLABS_API_KEY",)
    docs_url = "https://elevenlabs.io/docs/api-reference"

    BASE = "https://api.elevenlabs.io/v1"

    def _key(self) -> Optional[str]:
        return self.settings.get("api_key") or ELEVENLABS_API_KEY

    def is_connected(self) -> bool:
        return bool(self._key())

    def capabilities(self) -> Capabilities:
        return Capabilities(
            models=["eleven_multilingual_v2", "eleven_turbo_v2_5"],
            languages=["en", "hi", "es", "fr", "de", "ja", "zh", "pt", "it"],
            max_variations=1,
            cancellation=False,
            reports_progress=False,
            cost_estimation=True,
            notes="Per-character billing. Stability and similarity controls "
                  "are supported; explicit emotion selection is not.",
        )

    def verify_connection(self) -> dict:
        base = super().verify_connection()
        if base.get("error") and "not connected" in base["error"]:
            return base
        try:
            data = http.get_json(f"{self.BASE}/voices", provider=self.name,
                                 headers={"xi-api-key": self._key()},
                                 timeout=(10, 30))
            return {"ok": True, "verified": True,
                    "voices_seen": len(data.get("voices", []))}
        except ProviderError as exc:
            self._last_error = exc.message
            return {"ok": False, "verified": False, "error": exc.message}

    def list_voices(self, language: str = "") -> list[Voice]:
        if not self.is_connected():
            return []
        try:
            data = http.get_json(f"{self.BASE}/voices", provider=self.name,
                                 headers={"xi-api-key": self._key()},
                                 timeout=(10, 30))
        except ProviderError:
            return []

        voices = []
        for v in data.get("voices", []):
            labels = v.get("labels") or {}
            voices.append(Voice(
                id=v.get("voice_id", ""),
                name=v.get("name", ""),
                language=labels.get("language", "en"),
                gender=(labels.get("gender") or "").lower(),
                preview_url=v.get("preview_url", ""),
                provider=self.name,
            ))
        if language:
            voices = [v for v in voices if v.language.lower().startswith(language.lower())]
        return voices

    def estimate_cost(self, request=None) -> CostEstimate:
        """Character count is knowable; the per-character price depends on
        the account's plan, which the API does not expose. We report the
        billable units and say plainly that the rate is unknown."""
        text = getattr(request, "prompt", "") if request else ""
        return CostEstimate(
            amount=None, confidence="unknown",
            basis=f"{len(text)} characters billable; per-character rate "
                  f"depends on your ElevenLabs plan",
        )

    def generate_speech(self, text: str, voice_id: str = "", *,
                        language: str = "en", speed: float = 1.0,
                        **extra) -> GenerationStatus:
        if not self.is_connected():
            return GenerationStatus(
                state=JobState.FAILED,
                error="ElevenLabs not connected (set ELEVENLABS_API_KEY)")
        if not (text or "").strip():
            return GenerationStatus(state=JobState.FAILED,
                                    error="no text to synthesise")
        if not voice_id:
            return GenerationStatus(state=JobState.FAILED,
                                    error="no voice selected")

        payload = {
            "text": text,
            "model_id": extra.get("model") or "eleven_multilingual_v2",
            "voice_settings": {
                "stability": float(extra.get("stability", 0.5)),
                "similarity_boost": float(extra.get("similarity_boost", 0.75)),
            },
        }
        try:
            resp = http.request(
                "POST", f"{self.BASE}/text-to-speech/{voice_id}",
                provider=self.name,
                headers={"xi-api-key": self._key(),
                         "Content-Type": "application/json",
                         "Accept": "audio/mpeg"},
                json=payload, timeout=(10, 180),
            )
        except ProviderError as exc:
            return GenerationStatus(state=JobState.FAILED, error=exc.message)

        audio = resp.content
        if not audio:
            return GenerationStatus(state=JobState.FAILED,
                                    error="provider returned no audio")

        return GenerationStatus(
            state=JobState.COMPLETED, output_bytes=audio, mime="audio/mpeg",
            duration_s=measure_duration(audio, "audio/mpeg"), stage="completed",
        )


def _run_async(coro):
    """Run a coroutine from sync code, including inside a thread that may
    already own an event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


VOICE_PROVIDERS = [EdgeTTSProvider, ElevenLabsProvider]
