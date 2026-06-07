"""Phase 5a shared dataclasses for voice identification."""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Relation(str, Enum):
    SELF = "self"
    FAMILY = "family"
    FRIEND = "friend"
    PROFESSIONAL = "professional"
    STRANGER = "stranger"


@dataclass
class Person:
    """A registered person whose voice ULTRON can recognise."""
    name: str
    relation: Relation
    voiceprint: List[float]
    enrolled_at: float
    notes: str = ""

    @staticmethod
    def slug_for(name: str) -> str:
        """Normalise a name into a filesystem-safe lowercase slug.

        Rules:
          - lowercase
          - drop non-alphanumeric characters except spaces and hyphens
          - collapse whitespace runs into single hyphens
          - strip leading/trailing hyphens
        """
        s = (name or "").lower()
        s = re.sub(r"[^a-z0-9\s\-]", "", s)
        s = re.sub(r"\s+", "-", s.strip())
        s = re.sub(r"-+", "-", s)
        return s.strip("-")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "relation": self.relation.value,
            "voiceprint": list(self.voiceprint),
            "enrolled_at": self.enrolled_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Person":
        return cls(
            name=d["name"],
            relation=Relation(d["relation"]),
            voiceprint=list(d["voiceprint"]),
            enrolled_at=float(d["enrolled_at"]),
            notes=d.get("notes", ""),
        )


@dataclass
class RecognitionResult:
    """Output of speaker_diarizer.identify_speaker()."""
    name: Optional[str]
    similarity: float
    threshold: float

    @property
    def matched(self) -> bool:
        return self.name is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "similarity": self.similarity,
            "threshold": self.threshold,
            "matched": self.matched,
        }
