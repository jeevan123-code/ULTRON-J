"""Phase 5e shortcut dataclass."""
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Shortcut:
    """A learned slang/abbreviation mapping.

    `term` is the casual phrase Jeevan uses (e.g., "the wheat thing").
    `canonical` is the concrete name it refers to (e.g., "wheat-3d-explorer").
    """
    term: str
    canonical: str
    confidence: float
    created_at: float
    taught_explicitly: bool

    def normalised_term(self) -> str:
        """Lowercase + trimmed term, suitable as a registry key."""
        return self.term.strip().lower()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "term": self.term,
            "canonical": self.canonical,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "taught_explicitly": self.taught_explicitly,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Shortcut":
        return cls(
            term=d["term"],
            canonical=d["canonical"],
            confidence=float(d["confidence"]),
            created_at=float(d["created_at"]),
            taught_explicitly=bool(d["taught_explicitly"]),
        )
