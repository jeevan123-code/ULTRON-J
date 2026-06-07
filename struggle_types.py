"""Shared dataclasses for Phase 3a (passive screen watching + struggle detection)."""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional


class StuckKind(str, Enum):
    ERROR_PERSISTENT = "error_persistent"   # same error visible >= threshold
    IDLE_ON_ERROR = "idle_on_error"         # error visible AND no input change


class SensitivityKind(str, Enum):
    NONE = "none"
    BANKING = "banking"
    PASSWORD_FIELD = "password_field"
    SECRET_FILE = "secret_file"             # .env, credentials, etc.


@dataclass
class ScreenSnapshot:
    """A single observation of the active screen."""
    ts: float
    active_window: str
    error_text: str
    error_signature: str
    sensitivity: SensitivityKind = SensitivityKind.NONE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "active_window": self.active_window,
            "error_text": self.error_text,
            "error_signature": self.error_signature,
            "sensitivity": self.sensitivity.value,
        }


@dataclass
class StuckEvent:
    """A struggle signal emitted by struggle_detector."""
    kind: StuckKind
    first_seen_ts: float
    last_seen_ts: float
    duration_seconds: float
    snapshot: ScreenSnapshot

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "first_seen_ts": self.first_seen_ts,
            "last_seen_ts": self.last_seen_ts,
            "duration_seconds": self.duration_seconds,
            "snapshot": self.snapshot.to_dict(),
        }
