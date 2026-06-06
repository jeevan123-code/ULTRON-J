"""Source credibility tiering.

Maps a URL to a SourceTier so cross-check consensus can weight claims by trust.
Rules are deliberately conservative and based on domain patterns only — no
network calls, no LLM, fully deterministic.
"""
from typing import List, Tuple
from urllib.parse import urlparse

from research_types import SourceTier


# (domain_substring, tier)
# Order matters — first match wins. Put longest / most specific first.
_DOMAIN_RULES: List[Tuple[str, SourceTier]] = [
    # ACADEMIC
    ("arxiv.org", SourceTier.ACADEMIC),
    ("pubmed.ncbi.nlm.nih.gov", SourceTier.ACADEMIC),
    ("ncbi.nlm.nih.gov", SourceTier.ACADEMIC),
    ("nature.com", SourceTier.ACADEMIC),
    ("science.org", SourceTier.ACADEMIC),
    ("scholar.google.com", SourceTier.ACADEMIC),
    ("nih.gov", SourceTier.ACADEMIC),
    ("cdc.gov", SourceTier.ACADEMIC),
    ("who.int", SourceTier.ACADEMIC),
    ("nasa.gov", SourceTier.ACADEMIC),
    (".edu", SourceTier.ACADEMIC),
    (".gov", SourceTier.ACADEMIC),

    # JOURNALISM
    ("reuters.com", SourceTier.JOURNALISM),
    ("apnews.com", SourceTier.JOURNALISM),
    ("bbc.com", SourceTier.JOURNALISM),
    ("bbc.co.uk", SourceTier.JOURNALISM),
    ("nytimes.com", SourceTier.JOURNALISM),
    ("wsj.com", SourceTier.JOURNALISM),
    ("washingtonpost.com", SourceTier.JOURNALISM),
    ("theguardian.com", SourceTier.JOURNALISM),
    ("ft.com", SourceTier.JOURNALISM),
    ("bloomberg.com", SourceTier.JOURNALISM),
    ("afp.com", SourceTier.JOURNALISM),
    ("npr.org", SourceTier.JOURNALISM),

    # WIKIPEDIA
    ("wikipedia.org", SourceTier.WIKIPEDIA),

    # DOCS_OFFICIAL
    ("docs.python.org", SourceTier.DOCS_OFFICIAL),
    ("github.com", SourceTier.DOCS_OFFICIAL),
    ("gitlab.com", SourceTier.DOCS_OFFICIAL),
    ("kubernetes.io", SourceTier.DOCS_OFFICIAL),
    ("mozilla.org", SourceTier.DOCS_OFFICIAL),
    ("developer.mozilla.org", SourceTier.DOCS_OFFICIAL),

    # BLOG — explicit personal-blog platforms
    ("medium.com", SourceTier.BLOG),
    ("substack.com", SourceTier.BLOG),
    ("wordpress.com", SourceTier.BLOG),
    ("blogspot.com", SourceTier.BLOG),
]


def tier_for_url(url: str) -> SourceTier:
    """Return the SourceTier for a given URL.

    Falls back to GENERAL for unknown but well-formed URLs, and UNKNOWN for
    malformed input.
    """
    if not url or not isinstance(url, str):
        return SourceTier.UNKNOWN
    try:
        parsed = urlparse(url)
    except Exception:
        return SourceTier.UNKNOWN
    host = (parsed.hostname or "").lower()
    if not host:
        return SourceTier.UNKNOWN

    for needle, tier in _DOMAIN_RULES:
        if needle.startswith("."):
            if host.endswith(needle):
                return tier
        else:
            if needle in host:
                return tier
    return SourceTier.GENERAL


def consensus_confidence(tiers: List[SourceTier]) -> float:
    """Compute a 0.0..1.0 confidence score for a claim given the tiers it appears in.

    Logic:
      - confidence rises with both COUNT of supporting sources and their tier WEIGHT
      - normalised so two journalism sources confirm strongly, one blog source confirms weakly
    """
    if not tiers:
        return 0.0
    total_weight = sum(t.weight for t in tiers)
    confidence = total_weight / (total_weight + 2.0)
    return min(round(confidence, 3), 1.0)
