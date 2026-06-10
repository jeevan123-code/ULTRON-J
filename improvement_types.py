"""Phase 3c improvement suggestion types.

`Suggestion` is produced by `improvement_suggester.analyze(events)` when a
repetitive pattern is detected. `proactive_offer` / a future UI surface can
display the summary and use `template` to scaffold the actual script.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

from action_types import ActionEvent


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


@dataclass
class Suggestion:
    """A repetition pattern the suggester noticed.

    `kind` is a short slug (e.g., "batch_rename"). `template` names the
    automation scaffold to generate. `supporting_events` is the slice of
    ActionEvents the suggester used. `confidence` is in [0,1] (auto-clamped).
    """
    kind: str
    summary: str
    template: str
    supporting_events: List[ActionEvent] = field(default_factory=list)
    confidence: float = 0.5

    def __post_init__(self) -> None:
        self.confidence = _clamp(self.confidence)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "template": self.template,
            "supporting_events": [e.to_dict() for e in self.supporting_events],
            "confidence": self.confidence,
        }
