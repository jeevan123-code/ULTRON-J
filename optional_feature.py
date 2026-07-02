"""
optional_feature.py — classify "feature unavailable" vs "real crash".

Some routes depend on optional, environment-specific capabilities:
edge-tts for voice briefings, a display for screenshots, PortAudio/pyaudio
for microphone capture. When one of those is absent the route should report
HTTP 503 ("this feature is not available in degraded mode"), NOT 500 ("an
uncaught bug in our code"). The route_smoke contract treats 503 as acceptable
and 500 as a failure (tests/test_route_smoke.py), so misclassifying a missing
optional dependency as 500 turns a normal degraded environment into a test /
monitoring failure.

Usage in a route handler:

    from optional_feature import http_status_for

    try:
        ...optional-feature work...
    except Exception as e:
        return jsonify({"error": str(e)}), http_status_for(e)
"""

# Substrings (lower-cased) in an exception message that indicate a missing
# optional system dependency or an unavailable environment resource rather
# than a bug in our own code.
_DEPENDENCY_SIGNALS = (
    "edge-tts", "edge_tts",
    "no module named",
    "portaudio",
    "pyaudio",
    "sounddevice",
    "alsa",
    "no default output device", "no default input device", "no audio",
    "no display", "display name", "cannot connect to x", "$display",
    "libgl",
    "espeak",
    "ffmpeg",
    "whisper",
    "torch",
)


def unavailable_dependency(exc: BaseException) -> bool:
    """
    Return True when `exc` indicates a missing optional dependency or an
    unavailable environment resource (no display, no audio device) — i.e. a
    condition the operator can fix by installing something, not a code bug.
    """
    # A missing importable module is, by definition, an optional dependency
    # that is not installed.
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return True
    msg = str(exc).lower()
    return any(signal in msg for signal in _DEPENDENCY_SIGNALS)


def http_status_for(exc: BaseException) -> int:
    """503 if the failure is a missing optional dependency / resource, else 500."""
    return 503 if unavailable_dependency(exc) else 500
