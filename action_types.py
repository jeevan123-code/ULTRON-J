"""Phase 3c action event types.

`ActionEvent` records one user action (or system-observed action) at a point
in time. `action_log` collects them; `improvement_suggester` scans for
repetitive patterns and proposes automation.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class ActionKind(str, Enum):
    """Coarse-grained category of an observed user action."""
    FILE_RENAME = "file_rename"
    FILE_OPEN = "file_open"
    APP_LAUNCH = "app_launch"
    CLICK = "click"
    TYPE = "type"
    SHORTCUT_FIRE = "shortcut_fire"
    OTHER = "other"


@dataclass
class ActionEvent:
    """A single observed action.

    `target` is a short string identifier — a filename, an app name, a UI
    element label. `detail` carries any extra structured context the
    suggester might use (e.g., a rename's new name).
    """
    ts: float
    kind: ActionKind
    target: str
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind.value,
            "target": self.target,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionEvent":
        raw_kind = d.get("kind", "other")
        try:
            kind = ActionKind(raw_kind)
        except ValueError:
            kind = ActionKind.OTHER
        return cls(
            ts=float(d["ts"]),
            kind=kind,
            target=d.get("target", ""),
            detail=dict(d.get("detail") or {}),
        )
