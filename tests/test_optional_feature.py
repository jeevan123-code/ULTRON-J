"""Tests for optional_feature — degraded-mode (503) vs real-crash (500)
classification used by the voice-briefing routes."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from optional_feature import unavailable_dependency, http_status_for


def test_import_error_is_degraded():
    assert unavailable_dependency(ImportError("No module named 'edge_tts'"))
    assert unavailable_dependency(ModuleNotFoundError("No module named 'edge_tts'"))
    assert http_status_for(ImportError("x")) == 503


def test_known_dependency_message_signals_are_degraded():
    for msg in (
        "edge-tts is not installed",
        "PortAudio library not found",
        "no display name and no $DISPLAY environment variable",
        "libGL.so.1: cannot open shared object file",
        "ffmpeg not found",
    ):
        assert unavailable_dependency(RuntimeError(msg)), msg
        assert http_status_for(RuntimeError(msg)) == 503, msg


def test_real_bug_is_500():
    # A genuine code bug must NOT be masked as a degraded 503.
    assert not unavailable_dependency(KeyError("mood"))
    assert not unavailable_dependency(ValueError("invalid kind"))
    assert http_status_for(ZeroDivisionError("division by zero")) == 500
