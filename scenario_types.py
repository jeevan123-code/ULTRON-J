"""Phase 4 scenario types — multi-device named action bundles.

A `Scenario` couples a trigger phrase (e.g., "house party") with a list of
`ScenarioStep`s that fan out to existing device modules
(`computer_control`, `mobile_bridge`, `smart_home`, etc).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ScenarioStep:
    """One device action inside a Scenario.

    `target` names the device subsystem ("laptop", "phone", "smart_home", "tv").
    `action` is a short slug ("lock", "lights_off", "silence", ...).
    `args` is an arbitrary dict the coordinator hands to the dispatch fn.
    """
    target: str
    action: str
    args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"target": self.target, "action": self.action, "args": dict(self.args)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ScenarioStep":
        return cls(
            target=d["target"], action=d["action"],
            args=dict(d.get("args") or {}),
        )


@dataclass
class Scenario:
    """A named bundle of cross-device actions.

    Match incoming voice text with `matches_trigger`. The coordinator runs
    each step in order; one step failing does not abort the others.
    """
    name: str
    trigger_phrases: List[str]
    steps: List[ScenarioStep] = field(default_factory=list)

    def matches_trigger(self, text: str) -> bool:
        if not text:
            return False
        haystack = text.lower()
        for phrase in self.trigger_phrases:
            needle = (phrase or "").lower().strip()
            if needle and needle in haystack:
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "trigger_phrases": list(self.trigger_phrases),
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Scenario":
        return cls(
            name=d["name"],
            trigger_phrases=list(d.get("trigger_phrases") or []),
            steps=[ScenarioStep.from_dict(s) for s in d.get("steps") or []],
        )
