"""Phase 6 briefing delivery — fan out one text into multiple channels.

Each channel handler is a small indirection so tests can stub. Failures
on one channel never abort the others.
"""
from typing import Any, Dict, List


def _telegram_send(text: str) -> Dict[str, Any]:
    import mobile_bridge
    return mobile_bridge.send_message(text)


def _voice_say(text: str):
    import voice_engine
    return voice_engine.tts(text, mood="FOCUSED")


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase6][delivery] {msg}\n")
    except Exception:
        pass


def deliver(text: str, channels: List[str]) -> Dict[str, Any]:
    """Send `text` to each channel; return per-channel results."""
    results: Dict[str, Any] = {}
    for channel in channels or []:
        if channel == "telegram":
            try:
                res = _telegram_send(text)
                results["telegram"] = {"ok": True, "response": res}
            except Exception as e:
                _safe_log(f"telegram failed: {e!r}")
                results["telegram"] = {"ok": False, "error": repr(e)}
        elif channel == "voice":
            try:
                audio, provider = _voice_say(text)
                results["voice"] = {"ok": True, "provider": provider, "bytes": len(audio or b"")}
            except Exception as e:
                _safe_log(f"voice failed: {e!r}")
                results["voice"] = {"ok": False, "error": repr(e)}
        else:
            results[channel] = {"skipped": True, "reason": "unknown channel"}
    return results
