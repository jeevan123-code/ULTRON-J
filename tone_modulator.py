"""Tone Modulator — privacy-aware, mood-aware text rewriting.

Single entry point: `modulate(text, mood, privacy_mode) -> str`.

Order of operations:
    1. Privacy redaction (always applied when privacy_mode in REDACT_MODES)
    2. Mood adjustment (single-pass; soft preamble for TIRED, terse rewrite
       for FRUSTRATED; FOCUSED / NEUTRAL / RELAXED leave text unchanged).
"""
import re
from typing import Optional

from mood_types import MoodState


_REDACT_MODES = ("stranger_present", "professional")
_REDACTION_TOKEN = "[redacted]"


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}\b", re.IGNORECASE),
    re.compile(r"(?i)\b(?:password|passwd|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b[a-z_][a-z0-9_]*_(?:key|token|secret)\s*[:=]\s*\S+"),
    re.compile(r"/home/jeevan/[^\s)\]'\"]+"),
)

_TIRED_PREAMBLE = "Take your time, sir. "

_FRUSTRATED_FILLERS = (
    re.compile(r"^sir,?\s+", re.IGNORECASE),
    re.compile(r"^here'?s?\s+what\s+i\s+found\s*[:,]?\s+", re.IGNORECASE),
    re.compile(r"^let\s+me\s+(?:see|check|look)\s*[.,]?\s+", re.IGNORECASE),
    re.compile(r"^well,?\s+", re.IGNORECASE),
)


def _redact_secrets(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(_REDACTION_TOKEN, out)
    return out


def _soft_preamble(text: str) -> str:
    if text.startswith(_TIRED_PREAMBLE.strip()):
        return text
    return _TIRED_PREAMBLE + text


def _drop_filler(text: str) -> str:
    out = text
    for pat in _FRUSTRATED_FILLERS:
        new = pat.sub("", out, count=1)
        if new != out:
            out = new
            if out and out[0].islower():
                out = out[0].upper() + out[1:]
    return out


def modulate(text: Optional[str],
             mood: Optional[MoodState] = None,
             privacy_mode: Optional[str] = None) -> str:
    """Rewrite text according to mood and privacy mode. Empty input -> ''."""
    if not text:
        return ""

    out = text

    if privacy_mode in _REDACT_MODES:
        out = _redact_secrets(out)

    if mood == MoodState.TIRED:
        out = _soft_preamble(out)
    elif mood == MoodState.FRUSTRATED:
        out = _drop_filler(out)

    return out
