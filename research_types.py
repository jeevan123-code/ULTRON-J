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


import re as _re


_CITE_PATTERN = _re.compile(r"\s*\[\d+\]")


def _strip_citations(text: str) -> str:
    """Remove `[1]`, `[2]` style markers for voice friendliness."""
    return _CITE_PATTERN.sub("", text).strip()


def _split_into_sentences(text: str) -> List[str]:
    """Naive sentence split for card bullets / brief truncation."""
    parts = _re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def report_from_research_dict(query: str, d: Dict[str, Any]) -> "ResearchReport":
    """Convert a `research_engine.research()` dict into a typed ResearchReport.

    - Strips `[N]` citation markers from spoken brief (voice friendly)
    - Splits the engine's `answer` into card bullets (1 per sentence)
    - Builds one CitedFact per sentence, attaching all sources that the
      sentence's citation markers point to, with their inferred tiers
    """
    from source_credibility import tier_for_url, consensus_confidence

    answer = d.get("answer", "")
    sources = d.get("sources", [])
    source_by_n: Dict[int, Dict[str, Any]] = {s["n"]: s for s in sources}

    sentences = _split_into_sentences(answer)
    bullets = [_strip_citations(s) for s in sentences][:12]
    spoken_brief = _strip_citations(answer)

    facts: List[CitedFact] = []
    for sent in sentences:
        cite_ns = [int(m) for m in _re.findall(r"\[(\d+)\]", sent)]
        urls: List[str] = []
        tiers: List[SourceTier] = []
        for n in cite_ns:
            src = source_by_n.get(n)
            if not src:
                continue
            url = src.get("url", "")
            urls.append(url)
            tiers.append(tier_for_url(url))
        if not tiers:
            continue
        facts.append(CitedFact(
            text=_strip_citations(sent),
            source_urls=urls,
            tiers=tiers,
            confidence=consensus_confidence(tiers),
        ))

    return ResearchReport(
        query=query,
        spoken_brief=spoken_brief,
        card_bullets=bullets,
        facts=facts,
        sources=list(sources),
        contradictions=list(d.get("contradictions", [])),
        ms=int(d.get("ms", 0)),
    )
