"""Phase 6 briefing schedule type."""
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class BriefingSchedule:
    """One scheduled briefing.

    `cron_expr` is a 5-field cron string interpreted by `croniter`.
    `channels` lists delivery surfaces: "telegram", "voice".
    `include_worldfeed` toggles the world-event section.
    """
    id: str
    cron_expr: str
    created_at: float
    channels: List[str] = field(default_factory=lambda: ["telegram"])
    include_worldfeed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cron_expr": self.cron_expr,
            "created_at": self.created_at,
            "channels": list(self.channels),
            "include_worldfeed": self.include_worldfeed,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BriefingSchedule":
        return cls(
            id=d["id"],
            cron_expr=d["cron_expr"],
            created_at=float(d.get("created_at", 0.0)),
            channels=list(d.get("channels") or ["telegram"]),
            include_worldfeed=bool(d.get("include_worldfeed", True)),
        )
