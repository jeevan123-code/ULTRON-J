"""Phase 9 vision capture — webcam grab with a soft cv2 dependency.

`cv2` (OpenCV) is the canonical implementation. If it isn't installed,
`is_available()` returns False and `get_latest_frame()` returns None.
That's enough for the rest of ULTRON to keep running — the `look` action
simply yields a "no camera" observation instead of crashing.
"""
import time
import threading
from typing import Optional

from vision_types import VisionFrame


try:
    import cv2 as _cv2  # type: ignore
except Exception:
    _cv2 = None  # type: ignore


_lock = threading.RLock()
_camera_index = 0


def _now() -> float:
    return time.time()


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase9][vision_capture] {msg}\n")
    except Exception:
        pass


def _reset_for_test() -> None:
    """No persistent state today; reserved for future warm-cap caching."""
    pass


def is_available() -> bool:
    """True when cv2 is importable AND a camera-open call would be safe."""
    return _cv2 is not None


def set_camera_index(idx: int) -> None:
    global _camera_index
    with _lock:
        _camera_index = int(idx)


def get_latest_frame() -> Optional[VisionFrame]:
    """Grab one webcam frame. Returns None if cv2 missing or capture fails."""
    if _cv2 is None:
        return None
    try:
        cap = _cv2.VideoCapture(_camera_index)
        try:
            ok, frame = cap.read()
            if not ok or frame is None:
                return None
            shape = getattr(frame, "shape", None)
            if not shape or len(shape) < 2:
                return None
            height, width = int(shape[0]), int(shape[1])
            raw = frame.tobytes() if hasattr(frame, "tobytes") else b""
            return VisionFrame(ts=_now(), width=width, height=height, raw=raw)
        finally:
            try:
                cap.release()
            except Exception:
                pass
    except Exception as e:
        _safe_log(f"capture failed: {e!r}")
        return None
