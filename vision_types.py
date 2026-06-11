"""Phase 9 vision dataclasses.

`VisionFrame` is one captured webcam frame. `VisionObservation` is the
distilled summary the perception module produces — face count, motion
flag, average brightness, "is someone here" boolean. Both are small,
serialisable, and free of cv2 imports so anything that consumes them
works regardless of whether OpenCV is installed.
"""
from dataclasses import dataclass
from typing import Any, Dict, Tuple


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


@dataclass
class VisionFrame:
    """One captured camera frame.

    `raw` is the raw image bytes — interpretation is left to the
    perception layer (BGR for OpenCV; format-agnostic by default).
    """
    ts: float
    width: int
    height: int
    raw: bytes

    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)


@dataclass
class VisionObservation:
    """Summary of what perception saw in the latest frame(s)."""
    ts: float
    faces: int = 0
    motion: bool = False
    brightness: float = 0.0
    person_present: bool = False

    def __post_init__(self) -> None:
        self.brightness = _clamp(self.brightness)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "faces": self.faces,
            "motion": self.motion,
            "brightness": self.brightness,
            "person_present": self.person_present,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VisionObservation":
        return cls(
            ts=float(d.get("ts", 0.0)),
            faces=int(d.get("faces", 0)),
            motion=bool(d.get("motion", False)),
            brightness=float(d.get("brightness", 0.0)),
            person_present=bool(d.get("person_present", False)),
        )
