"""Shared dataclasses for the conversation/reasoning layer.

These types are the contract between:
  - compound_intent_parser  (produces ParsedUtterance)
  - conversation_intelligence (consumes ParsedUtterance, enriches Intent)
  - reasoning_layer (consumes enriched ParsedUtterance, produces ExecutionPlan)
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class IntentKind(str, Enum):
    AFFIRM = "affirm"
    DENY = "deny"
    DEFER = "defer"
    RESEARCH = "research"
    COMMAND = "command"
    CHAT = "chat"
    CLARIFY = "clarify"


class ModifierKind(str, Enum):
    ADD = "add"
    EXCLUDE = "exclude"
    PRE_CHECK = "pre_check"
    PRIORITY = "priority"
    SWITCH_TO = "switch_to"
    MODIFY = "modify"


@dataclass
class Intent:
    kind: IntentKind
    payload: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind.value, "payload": self.payload, "confidence": self.confidence}


@dataclass
class Modifier:
    kind: ModifierKind
    value: Any

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind.value, "value": self.value}


@dataclass
class ParsedUtterance:
    raw: str
    primary: Intent
    modifiers: List[Modifier] = field(default_factory=list)
    tone: str = "neutral"  # casual | urgent | frustrated | tired | neutral
    references: Dict[str, Any] = field(default_factory=dict)  # resolved "that thing" -> concrete

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "primary": self.primary.to_dict(),
            "modifiers": [m.to_dict() for m in self.modifiers],
            "tone": self.tone,
            "references": self.references,
        }


@dataclass
class ExecutionPlan:
    steps: List[Dict[str, Any]] = field(default_factory=list)
    pre_checks: List[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
