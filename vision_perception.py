"""Phase 9 vision perception — VisionFrame -> VisionObservation.

Lightweight, opt-in. Uses OpenCV's Haar cascade face detector and a
between-frame brightness delta to flag motion. No heavyweight models,
no GPU. If cv2 is missing, returns a "safe" observation with everything
zeroed out instead of crashing.
"""
import threading
from typing import Any, Optional

from vision_types import VisionFrame, VisionObservation


try:
    import cv2 as _cv2  # type: ignore
except Exception:
    _cv2 = None  # type: ignore


_lock = threading.RLock()
_prev_brightness: Optional[float] = None
_MOTION_DELTA_THRESHOLD = 0.15  # 15% brightness shift between frames


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase9][vision_perception] {msg}\n")
    except Exception:
        pass


def _reset_for_test() -> None:
    global _prev_brightness
    with _lock:
        _prev_brightness = None


def _frame_to_array(frame: VisionFrame):
    """Convert raw bytes back to a numpy array via cv2.imdecode.

    Wrapped as a module-level seam so tests can stub without numpy.
    """
    import numpy as _np  # type: ignore
    import cv2 as _local_cv2  # type: ignore
    arr = _np.frombuffer(frame.raw, dtype=_np.uint8)
    decoded = _local_cv2.imdecode(arr, _local_cv2.IMREAD_COLOR)
    return decoded if decoded is not None else arr


def observe(frame: Optional[VisionFrame]) -> Optional[VisionObservation]:
    """Distil one frame into a VisionObservation."""
    global _prev_brightness
    if frame is None:
        return None

    if _cv2 is None:
        return VisionObservation(ts=frame.ts)

    try:
        arr = _frame_to_array(frame)
        try:
            mean_val = float(arr.mean())
        except Exception:
            mean_val = 0.0
        brightness = max(0.0, min(1.0, mean_val / 255.0))

        # Motion: compare to previous brightness (cheap, no histogram)
        motion = False
        with _lock:
            if _prev_brightness is not None:
                if abs(brightness - _prev_brightness) >= _MOTION_DELTA_THRESHOLD:
                    motion = True
            _prev_brightness = brightness

        # Face detection via Haar cascade. Path resolution is best-effort:
        # cv2 ships its data dir with the package; if it's missing, the
        # CascadeClassifier returns an empty detector that detects nothing.
        try:
            gray = _cv2.cvtColor(arr, _cv2.COLOR_BGR2GRAY)
        except Exception:
            gray = arr
        try:
            cascade_path = ""
            data = getattr(_cv2, "data", None)
            if data is not None:
                cascade_path = getattr(data, "haarcascades", "") + "haarcascade_frontalface_default.xml"
            detector = _cv2.CascadeClassifier(cascade_path)
            faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)
            face_count = len(faces) if faces is not None else 0
        except Exception as e:
            _safe_log(f"face detect failed: {e!r}")
            face_count = 0

        return VisionObservation(
            ts=frame.ts,
            faces=face_count,
            motion=motion,
            brightness=brightness,
            person_present=(face_count > 0),
        )
    except Exception as e:
        _safe_log(f"observe failed: {e!r}")
        return VisionObservation(ts=frame.ts)
