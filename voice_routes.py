"""
voice_routes.py - Flask blueprint for /voice and /api/voice/* endpoints.

Extracted from app.py during the Task 2 blueprint split. Behavior is
byte-for-byte identical to the original handlers in app.py (lines 916-1357);
only the decorator changed from @app.route to @voice_bp.route.

Routes:
  /voice                    GET   - voice UI page
  /api/voice/status         GET   - voice system capabilities
  /api/voice/speak          POST  - text -> speech audio
  /api/voice/transcribe     POST  - audio -> text
  /api/voice/chat           POST  - full audio conversation (audio in -> audio out)
  /api/voice/briefing       GET   - morning/evening briefing audio
  /api/voice/log            GET   - recent voice interaction log
  /api/voice/stream_chat    POST  - streaming voice chat (SSE)

A few app-level helpers (get_mode, set_mode, needs_search,
_extract_entities_from_message) live in app.py. They are imported lazily
inside each handler to avoid circular imports — app.py imports voice_routes
at register time, which is before its own helpers would be visible to a
top-level `from app import ...` here.
"""

import json
import base64

from flask import Blueprint, render_template, request, jsonify, Response

# ── Mirror app.py optional-import pattern for voice_engine ─────────────────────
try:
    from voice_engine import (
        tts, stt, get_voice_status, get_voice_log,
        parse_voice_command, execute_voice_command,
        generate_voice_briefing, prepare_for_tts,
        stream_tts_from_llm,
    )
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    def tts(text, mood="FOCUSED", provider="auto"): raise RuntimeError("voice_engine not available")
    def stt(audio, provider="auto"): return {"text": "", "error": "voice_engine not available"}
    def get_voice_status(): return {"ready": False, "error": "edge-tts not installed"}
    def get_voice_log(n=20): return []
    def parse_voice_command(text): return None
    def execute_voice_command(cmd): return "Voice unavailable."
    def generate_voice_briefing(kind): return ""
    def stream_tts_from_llm(gen, mood="FOCUSED"): return iter([])

# ── Intelligence core (optional) ───────────────────────────────────────────────
try:
    from intelligence_core import think_and_stream
    INTELLIGENCE_AVAILABLE = True
except ImportError:
    INTELLIGENCE_AVAILABLE = False

# ── Module-level deps that are always available ────────────────────────────────
from config import STREAM_HEADERS
from memory import sqlite_get_history, sqlite_save_message, store_episode, record_activity
from personality import get_mood, get_mood_icon, trigger_mood_change, drain_energy
from perception import build_perception_context
from llm_engine import stream_llm
from task_orchestrator import orchestrate


voice_bp = Blueprint("voice", __name__)


@voice_bp.route("/voice")
def voice_page():
    """Serve the JARVIS-like voice interface."""
    return render_template("voice.html")


@voice_bp.route("/api/voice/status", methods=["GET"])
def voice_status():
    """Return voice system capabilities."""
    if not VOICE_AVAILABLE:
        return jsonify({"ready": False, "error": "Install edge-tts: pip install edge-tts"})
    status = get_voice_status()
    status["voice_available"] = VOICE_AVAILABLE
    return jsonify(status)


@voice_bp.route("/api/voice/speak", methods=["POST"])
def api_voice_speak():
    """
    Convert text to speech audio.
    Body: {"text": "...", "mood": "FOCUSED", "provider": "auto"}
    Returns: MP3 audio bytes with X-Mood header.
    """
    if not VOICE_AVAILABLE:
        return jsonify({"error": "Voice not available. pip install edge-tts"}), 503

    data     = request.json or {}
    text     = data.get("text", "").strip()
    mood     = data.get("mood") or get_mood()
    provider = data.get("provider", "auto")

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        audio, used_provider = tts(text, mood=mood, provider=provider)
        return Response(
            audio,
            mimetype="audio/mpeg",
            headers={
                "X-Mood":          mood,
                "X-TTS-Provider":  used_provider,
                "X-Text-Length":   str(len(text)),
                "Access-Control-Expose-Headers": "X-Mood, X-TTS-Provider, X-Text-Length",
            },
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@voice_bp.route("/api/voice/transcribe", methods=["POST"])
def api_voice_transcribe():
    """
    Transcribe audio to text.
    Body: multipart/form-data with 'audio' file field.
    Returns: {"text": "...", "confidence": 0.9, "provider": "..."}
    """
    if not VOICE_AVAILABLE:
        return jsonify({"error": "Voice not available"}), 503

    if "audio" not in request.files:
        return jsonify({"error": "No audio file in request. Use field name 'audio'"}), 400

    audio_bytes = request.files["audio"].read()
    if not audio_bytes:
        return jsonify({"error": "Empty audio file"}), 400

    result = stt(audio_bytes)
    return jsonify(result)


@voice_bp.route("/api/voice/chat", methods=["POST"])
def api_voice_chat():
    """
    Full voice conversation: audio in -> LLM -> audio out.

    Body: multipart/form-data
      - audio:      audio file (webm/wav/mp3)
      - session_id: optional session identifier

    Returns: MP3 audio with headers:
      X-Transcription:  what Jeevan said
      X-Response-Text:  Ultron's text response
      X-Mood:           current mood
      X-Confidence:     STT confidence
      X-Voice-Command:  if a fast-path command was matched
    """
    if not VOICE_AVAILABLE:
        return jsonify({"error": "Voice not available. pip install edge-tts"}), 503

    if "audio" not in request.files:
        return jsonify({"error": "No audio file"}), 400

    audio_bytes = request.files["audio"].read()
    session_id  = request.form.get("session_id", "voice_default")
    temperature = float(request.form.get("temperature", 0.7))

    if not audio_bytes:
        return jsonify({"error": "Empty audio"}), 400

    # Lazy import — these helpers live in app.py; importing at module load
    # would create a circular import.
    from app import get_mode, set_mode, needs_search, _extract_entities_from_message

    # ── Step 1: Transcribe ────────────────────────────────────────────────────
    stt_result  = stt(audio_bytes)
    user_text   = stt_result.get("text", "").strip()
    confidence  = stt_result.get("confidence", 0)

    if not user_text:
        # Nothing heard - return silence indicator
        try:
            audio, _ = tts("I didn't catch that. Could you repeat?", mood=get_mood())
            return Response(
                audio,
                mimetype="audio/mpeg",
                headers={
                    "X-Transcription":  "",
                    "X-Response-Text":  "I didn't catch that.",
                    "X-Mood":           get_mood(),
                    "X-Confidence":     "0",
                    "X-Voice-Command":  "",
                    "Access-Control-Expose-Headers": "X-Transcription,X-Response-Text,X-Mood,X-Confidence,X-Voice-Command",
                },
            )
        except Exception:
            return jsonify({"error": "STT returned empty text"}), 422

    # ── Step 2: Check for fast-path voice commands ────────────────────────────
    voice_cmd = parse_voice_command(user_text)
    mood      = get_mood()

    # ── Step 2a: Orchestrator intercept (screenshot, open app, YouTube, etc.) ─
    _orch = orchestrate(user_text, session_id=session_id)
    if _orch.get("action_taken") and not _orch.get("passthrough"):
        response_text = _orch.get("message") or "Done."
        try:
            audio, used_provider = tts(response_text, mood=mood)
            return Response(
                audio,
                mimetype="audio/mpeg",
                headers={
                    "X-Transcription": user_text,
                    "X-Response-Text": response_text,
                    "X-Mood":          mood,
                    "X-Confidence":    str(round(confidence, 2)),
                    "X-Voice-Command": _orch.get("action_taken", ""),
                    "Access-Control-Expose-Headers": "X-Transcription,X-Response-Text,X-Mood,X-Confidence,X-Voice-Command",
                },
            )
        except Exception as e:
            return jsonify({"error": f"TTS failed: {e}", "text_response": response_text}), 500

    if voice_cmd:
        response_text = execute_voice_command(voice_cmd)
        # Handle mode switches that modify app state
        if voice_cmd.startswith("MODE:"):
            set_mode(voice_cmd.split(":")[1])
        try:
            audio, _ = tts(response_text, mood=mood)
            return Response(
                audio,
                mimetype="audio/mpeg",
                headers={
                    "X-Transcription": user_text,
                    "X-Response-Text": response_text,
                    "X-Mood":          mood,
                    "X-Confidence":    str(round(confidence, 2)),
                    "X-Voice-Command": voice_cmd,
                    "Access-Control-Expose-Headers": "X-Transcription,X-Response-Text,X-Mood,X-Confidence,X-Voice-Command",
                },
            )
        except Exception as e:
            return jsonify({"error": f"TTS failed: {e}"}), 500

    # ── Step 3: Full LLM response ─────────────────────────────────────────────
    full_response = ""

    try:
        # Reuse existing cloud chat logic
        _extract_entities_from_message(user_text)
        record_activity(topic=user_text[:30], mode=get_mode(), session_id=session_id)

        history_rows = sqlite_get_history(session_id)
        messages     = [{"role": r, "content": m} for r, m in history_rows]
        messages.append({"role": "user", "content": user_text})

        trigger_mood_change("search_started") if needs_search(user_text) else None

        # Collect full response (non-streaming for voice - we need complete text before TTS)
        if INTELLIGENCE_AVAILABLE:
            for chunk in think_and_stream(user_text, session_id, history_rows, temperature):
                if chunk.startswith("data: "):
                    try:
                        d = json.loads(chunk[6:])
                        if d.get("_full"):
                            full_response = d["_full"]
                        elif d.get("token") and d.get("type") != "status":
                            full_response += d["token"]
                    except Exception:
                        pass
        else:
            perception_ctx = build_perception_context()
            extra_ctx = (perception_ctx or "") + "\n[VOICE MODE: Keep response under 3 sentences. No markdown.]"
            for chunk in stream_llm(messages, temperature=temperature, extra_context=extra_ctx):
                if chunk.startswith("data: "):
                    try:
                        d = json.loads(chunk[6:])
                        if d.get("_full"):
                            full_response = d["_full"]
                        elif d.get("token"):
                            full_response += d["token"]
                    except Exception:
                        pass

        if not full_response:
            full_response = "I had trouble generating a response. Please try again."

        # Save to memory
        sqlite_save_message(session_id, "user", user_text)
        sqlite_save_message(session_id, "assistant", full_response)
        store_episode(
            kind="voice_conversation",
            summary=f"[VOICE] {user_text[:80]}",
            detail=f"Response: {full_response[:300]}",
            valence=0.0,
            importance=0.3,
            session_id=session_id,
        )
        drain_energy(0.03)

    except Exception as e:
        full_response = f"System error: {str(e)[:100]}"

    # ── Step 4: Convert response to speech ────────────────────────────────────
    mood = get_mood()   # re-read (may have changed)
    try:
        audio, used_provider = tts(full_response, mood=mood)
    except Exception as e:
        return jsonify({
            "error":        f"TTS failed: {e}",
            "text_response": full_response,
            "transcription": user_text,
        }), 500

    return Response(
        audio,
        mimetype="audio/mpeg",
        headers={
            "X-Transcription": user_text,
            "X-Response-Text": full_response[:500],
            "X-Mood":          mood,
            "X-Mood-Icon":     get_mood_icon(),
            "X-Confidence":    str(round(confidence, 2)),
            "X-TTS-Provider":  used_provider,
            "X-Voice-Command": "",
            "Access-Control-Expose-Headers": (
                "X-Transcription,X-Response-Text,X-Mood,X-Mood-Icon,"
                "X-Confidence,X-TTS-Provider,X-Voice-Command"
            ),
        },
    )


@voice_bp.route("/api/voice/briefing", methods=["GET"])
def api_voice_briefing():
    """
    Get morning/evening briefing as audio.
    Query: ?kind=morning or ?kind=evening
    Returns: MP3 audio briefing
    """
    if not VOICE_AVAILABLE:
        return jsonify({"error": "Voice not available"}), 503

    kind = request.args.get("kind", "morning")
    mood = get_mood()

    try:
        from voice_engine import generate_voice_briefing
        briefing_text = generate_voice_briefing(kind)
        audio, _ = tts(briefing_text, mood=mood)
        return Response(
            audio,
            mimetype="audio/mpeg",
            headers={
                "X-Briefing-Text": briefing_text[:500],
                "X-Mood":          mood,
                "Access-Control-Expose-Headers": "X-Briefing-Text, X-Mood",
            },
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@voice_bp.route("/api/voice/log", methods=["GET"])
def api_voice_log():
    """Return recent voice interaction log."""
    if not VOICE_AVAILABLE:
        return jsonify({"log": [], "error": "Voice not available"})
    n = int(request.args.get("n", 20))
    return jsonify({"log": get_voice_log(n), "count": n})


# =============================================================================
# STREAMING VOICE CHAT - /api/voice/stream_chat
# THE KEY UPGRADE: First audio plays in ~2s instead of 10-15s
# Flow: audio -> STT -> LLM stream -> sentence -> TTS -> SSE audio chunk -> browser plays
# =============================================================================

@voice_bp.route("/api/voice/stream_chat", methods=["POST"])
def api_voice_stream_chat():
    """
    Streaming voice conversation.
    Audio in -> STT -> LLM stream -> sentence TTS -> audio chunks via SSE.

    Browser plays each sentence as it arrives - first audio in ~2s.

    Body: multipart/form-data
      - audio:      audio file
      - session_id: optional

    SSE event types:
      {"type": "transcript",  "text": "...", "confidence": 0.9}
      {"type": "text_token",  "token": "..."}          - LLM token for display
      {"type": "sentence",    "text": "...", "audio_b64": "...", "index": N}
      {"type": "text_only",   "text": "...", "index": N}  - TTS failed, text only
      {"type": "command",     "cmd": "...", "audio_b64": "..."}
      {"type": "mood",        "mood": "...", "icon": "..."}
      {"type": "done",        "full_text": "..."}
      {"type": "error",       "msg": "..."}
    """
    if not VOICE_AVAILABLE:
        return jsonify({"error": "Voice not available. pip install edge-tts aiohttp"}), 503

    if "audio" not in request.files:
        return jsonify({"error": "No audio file in request"}), 400

    audio_bytes = request.files["audio"].read()
    session_id  = request.form.get("session_id", "voice_stream")
    temperature = float(request.form.get("temperature", 0.7))

    if not audio_bytes:
        return jsonify({"error": "Empty audio"}), 400

    # Identity gate — log-only unless ULTRON_VOICE_IDENTITY_ENFORCE=1.
    # Fail-open on any error so this can never lock the enrolled owner out.
    try:
        from voice_engine import verify_caller_identity
        _id = verify_caller_identity(audio_bytes, format_hint="webm")
        if _id.get("enforced") and not _id.get("allow", True):
            return jsonify({
                "error":      "Voice does not match enrolled owner",
                "similarity": _id.get("similarity"),
                "threshold":  _id.get("threshold"),
            }), 403
    except Exception:
        pass  # identity-check failure must never block voice

    # Lazy import - app.py helpers
    from app import get_mode, set_mode, needs_search, _extract_entities_from_message

    def generate():
        # ── Step 1: Transcribe ────────────────────────────────────────────────
        stt_result = stt(audio_bytes)
        user_text  = stt_result.get("text", "").strip()
        confidence = stt_result.get("confidence", 0)

        if not user_text:
            yield f"data: {json.dumps({'type': 'error', 'msg': 'No speech detected — try again'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'transcript', 'text': user_text, 'confidence': round(confidence, 2)})}\n\n"

        mood = get_mood()
        yield f"data: {json.dumps({'type': 'mood', 'mood': mood, 'icon': get_mood_icon()})}\n\n"

        # ── Step 2: Fast-path voice commands ─────────────────────────────────
        from voice_commands_upgrade import parse_upgraded_voice_command, execute_upgraded_voice_command
        voice_cmd = parse_upgraded_voice_command(user_text)
        if voice_cmd:
            response_text = execute_upgraded_voice_command(voice_cmd, session_id=session_id)
            # Handle mode switch side effects
            if voice_cmd.startswith("MODE:"):
                set_mode(voice_cmd.split(":", 1)[1])
            try:
                audio_out, prov = tts(response_text, mood=mood)
                yield f"data: {json.dumps({'type': 'command', 'cmd': voice_cmd, 'text': response_text, 'audio_b64': base64.b64encode(audio_out).decode(), 'provider': prov})}\n\n"
            except Exception:
                yield f"data: {json.dumps({'type': 'text_only', 'text': response_text, 'index': 0})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'full_text': response_text})}\n\n"
            return

        # ── Step 2b: Orchestrator intercept ──────────────────────────────────
        _orch = orchestrate(user_text, session_id=session_id)
        if _orch.get("action_taken") and not _orch.get("passthrough"):
            response_text = _orch.get("message") or "Done."
            try:
                audio_out, prov = tts(response_text, mood=mood)
                yield f"data: {json.dumps({'type': 'command', 'cmd': _orch.get('action_taken', ''), 'text': response_text, 'audio_b64': base64.b64encode(audio_out).decode(), 'provider': prov})}\n\n"
            except Exception:
                yield f"data: {json.dumps({'type': 'text_only', 'text': response_text, 'index': 0})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'full_text': response_text})}\n\n"
            return

        # ── Step 3: LLM + streaming TTS ──────────────────────────────────────
        _extract_entities_from_message(user_text)
        record_activity(topic=user_text[:30], mode=get_mode(), session_id=session_id)

        history_rows = sqlite_get_history(session_id)
        messages     = [{"role": r, "content": m} for r, m in history_rows]
        messages.append({"role": "user", "content": user_text})

        if needs_search(user_text):
            trigger_mood_change("search_started")

        if INTELLIGENCE_AVAILABLE:
            llm_gen = think_and_stream(user_text, session_id, history_rows, temperature)
        else:
            perception_ctx = build_perception_context()
            extra_ctx = (
                (perception_ctx or "") +
                "\n[VOICE MODE: Use short, clear sentences. Each sentence should be self-contained. No markdown.]"
            )
            llm_gen = stream_llm(messages, extra_context=extra_ctx)
        full_text  = ""

        for chunk in stream_tts_from_llm(llm_gen, mood=mood):
            chunk_type = chunk.get("type")

            if chunk_type == "text_token":
                yield f"data: {json.dumps(chunk)}\n\n"

            elif chunk_type in ("sentence", "text_only"):
                if chunk_type == "sentence":
                    full_text += chunk.get("text", "") + " "
                yield f"data: {json.dumps(chunk)}\n\n"

            elif chunk_type == "done":
                full_text = chunk.get("full_text", full_text).strip()
                # Save to memory
                if full_text:
                    sqlite_save_message(session_id, "user", user_text)
                    sqlite_save_message(session_id, "assistant", full_text)
                    store_episode(
                        kind="voice_stream",
                        summary=f"[VOICE] {user_text[:80]}",
                        detail=full_text[:300],
                        valence=0.0,
                        importance=0.3,
                        session_id=session_id,
                    )
                    drain_energy(0.03)
                new_mood = get_mood()
                yield f"data: {json.dumps({'type': 'done', 'full_text': full_text, 'mood': new_mood, 'icon': get_mood_icon()})}\n\n"
                return

            elif chunk_type == "error":
                yield f"data: {json.dumps(chunk)}\n\n"
                return

        yield f"data: {json.dumps({'type': 'done', 'full_text': full_text.strip()})}\n\n"

    return Response(generate(), content_type="text/event-stream", headers=STREAM_HEADERS)
