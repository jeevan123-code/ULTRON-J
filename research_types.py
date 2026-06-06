"""Shared dataclasses for Phase 2a (agentic research pipeline)."""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceTier(str, Enum):
    """Credibility tier assigned to a fetched source.

    `.value` is the lowercase string label (used in JSON serialisation).
    `.weight` is the integer trust score (used for consensus math).
    Higher weight = more trusted.
    """
    ACADEMIC = "academic"        # arXiv, PubMed, gov, peer review
    JOURNALISM = "journalism"    # Reuters, BBC, AP, AFP, NYT
    WIKIPEDIA = "wikipedia"
    DOCS_OFFICIAL = "docs_official"  # github.com/<org>, docs.python.org, etc.
    GENERAL = "general"          # everything else credible
    BLOG = "blog"                # personal/opinion
    UNKNOWN = "unknown"

    @property
    def weight(self) -> int:
        return _TIER_WEIGHTS[self.name]


_TIER_WEIGHTS = {
    "ACADEMIC": 5,
    "JOURNALISM": 4,
    "WIKIPEDIA": 3,
    "DOCS_OFFICIAL": 3,
    "GENERAL": 2,
    "BLOG": 1,
    "UNKNOWN": 0,
}


@dataclass
class CitedFact:
    """A single atomic claim extracted from research output, with provenance."""
    text: str
    source_urls: List[str]
    tiers: List[SourceTier]
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "source_urls": list(self.source_urls),
            "tiers": [t.value for t in self.tiers],
            "confidence": self.confidence,
        }


@dataclass
class ResearchReport:
    """Final research output suitable for delivery + storage."""
    query: str
    spoken_brief: str
    card_bullets: List[str]
    facts: List[CitedFact]
    sources: List[Dict[str, Any]]
    contradictions: List[Dict[str, Any]]
    ms: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "spoken_brief": self.spoken_brief,
            "card_bullets": list(self.card_bullets),
            "facts": [f.to_dict() for f in self.facts],
            "sources": list(self.sources),
            "contradictions": list(self.contradictions),
            "ms": self.ms,
        }


@dataclass
class DeliveryEnvelope:
    """A report + routing flags telling the delivery manager what to do."""
    report: ResearchReport
    route_voice: bool = True
    route_card: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report": self.report.to_dict(),
            "route_voice": self.route_voice,
            "route_card": self.route_card,
        }
