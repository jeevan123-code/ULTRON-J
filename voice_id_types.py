"""Phase 5b shared dataclasses."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from person_types import Relation


@dataclass
class StrangerEvent:
    """Captured when an unrecognised voice is detected."""
    embedding: List[float]
    audio_path: str
    detected_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "embedding": list(self.embedding),
            "audio_path": self.audio_path,
            "detected_at": self.detected_at,
        }


@dataclass
class ParsedNameRelation:
    """Output of name_relation_parser.parse_name_relation()."""
    name: Optional[str]
    relation: Relation

    @property
    def is_resolved(self) -> bool:
        return self.name is not None and bool(self.name.strip())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "relation": self.relation.value,
            "resolved": self.is_resolved,
        }
