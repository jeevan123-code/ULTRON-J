"""Phase 14 — types for the self-authored goal daemon.

A `GoalProposal` is a goal Ultron came up with ON ITS OWN by observing its
environment. Proposals are pure data; `goal_author` decides whether to create
a real goal from one, park it for approval, or drop it.

`SafetyTier` is the Tier-4 seed: every proposal is classified before it can
lead to action.
    GREEN — read-only / additive (research, KB write, notify). Auto-allowed.
    AMBER — touches user data / apps / external services. Needs approval.
    RED   — destructive / code-exec / self-modify / third-party send / spend.
            Never self-authored; dropped.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class SafetyTier(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


def _normalise(text: str) -> str:
    """Lowercase + collapse whitespace — used for stable dedup keys."""
    return " ".join((text or "").lower().split())


@dataclass
class GoalProposal:
    """A goal Ultron proposes to itself from an observation."""
    title: str
    description: str
    rationale: str                 # WHY Ultron thinks this is worth doing
    trigger: str                   # which detector fired (e.g. "repeated_failure")
    subject: str                   # what the goal is about (drives dedup)
    priority: str = "medium"       # Priority.* value
    confidence: float = 0.5        # 0..1
    category: str = "research"     # research|automate|cleanup|replan -> safety tier
    dedup_key: str = ""            # computed from trigger+subject if empty

    def __post_init__(self) -> None:
        if not self.dedup_key:
            self.dedup_key = f"{self.trigger}:{_normalise(self.subject)}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "trigger": self.trigger,
            "subject": self.subject,
            "priority": self.priority,
            "confidence": self.confidence,
            "category": self.category,
            "dedup_key": self.dedup_key,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GoalProposal":
        return cls(
            title=d["title"],
            description=d["description"],
            rationale=d.get("rationale", ""),
            trigger=d.get("trigger", ""),
            subject=d.get("subject", ""),
            priority=d.get("priority", "medium"),
            confidence=float(d.get("confidence", 0.5)),
            category=d.get("category", "research"),
            dedup_key=d.get("dedup_key", ""),
        )
