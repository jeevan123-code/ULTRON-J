"""Implicit Shortcut Learner.

Detects probable (slang → canonical) shortcut mappings by observing
co-occurrence across a buffer of utterances. Pure logic — no LLM, no I/O.

Pipeline:
  1. For each utterance, extract:
       - slang candidates: "the X" or "that X" where X is 1-3 words
       - canonical candidates: hyphenated identifiers like wheat-3d-explorer
  2. Aggregate (slang, canonical) co-occurrence counts across utterances.
  3. Pairs whose co-occurrence count crosses the threshold are returned
     as `ProposedShortcut` records, ranked by confidence.

Designed for the Phase 2b `conversation_listener` buffer: callers pass
`drain_unprocessed()`-style text lists.
"""
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Set


# ─────────────────────────────────────────────────────────────────────────────
# Candidate extraction
# ─────────────────────────────────────────────────────────────────────────────

# Hyphenated identifier: at least one hyphen separating alphanumeric chunks.
_CANONICAL_RE = re.compile(r"\b[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)+\b")

# Stop-words that mark the END of a slang phrase. Used as a negative lookahead
# inside the slang regex so "the wheat thing for me" yields "the wheat thing"
# (not "the wheat thing for me").
_STOP_AFTER_NOUN = (
    "in", "on", "at", "of", "for", "to", "with",
    "and", "or", "but", "from", "by", "is", "are",
    "was", "were", "has", "have", "will", "after",
    "before", "as", "than", "if", "when", "while",
    "today", "tomorrow", "yesterday", "now", "soon",
    "here", "there", "again", "also", "just", "only",
    "needs", "needed", "need",
)
_STOP_PATTERN = "|".join(_STOP_AFTER_NOUN)

# "the X" or "that X" where each X is a 1-3 word lowercase noun phrase.
# Negative lookahead prevents preposition/conjunction tokens from being absorbed.
_SLANG_RE = re.compile(
    rf"\b(?:the|that)(?:\s+(?!(?:{_STOP_PATTERN})\b)[a-zA-Z]+){{1,3}}\b",
    re.IGNORECASE,
)


def extract_canonical_candidates(text: str) -> Set[str]:
    """Hyphenated identifiers found in `text`."""
    if not text:
        return set()
    return {m.group(0) for m in _CANONICAL_RE.finditer(text)}


def extract_slang_candidates(text: str) -> Set[str]:
    """Lowercased 'the X' / 'that X' slang phrases found in `text`."""
    if not text:
        return set()
    return {m.group(0).lower() for m in _SLANG_RE.finditer(text)}


# ─────────────────────────────────────────────────────────────────────────────
# Proposal
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProposedShortcut:
    """A candidate shortcut surfaced by co-occurrence analysis."""
    slang: str
    canonical: str
    cooccurrences: int
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slang": self.slang,
            "canonical": self.canonical,
            "cooccurrences": self.cooccurrences,
            "confidence": self.confidence,
        }


def propose_shortcuts(
    utterances: List[str],
    min_cooccurrence: int = 3,
) -> List[ProposedShortcut]:
    """Return shortcut proposals from a buffer of utterances.

    A pair (slang, canonical) is proposed when it co-occurs in at least
    `min_cooccurrence` utterances. Confidence is `count / (count + 2)`,
    so 3 co-occurrences → 0.6, 10 → ~0.83, 50 → ~0.96.
    """
    if not utterances:
        return []

    pair_counts: Counter = Counter()
    for utt in utterances:
        if not utt:
            continue
        slangs = extract_slang_candidates(utt)
        canonicals = extract_canonical_candidates(utt)
        for s in slangs:
            for c in canonicals:
                pair_counts[(s, c)] += 1

    out: List[ProposedShortcut] = []
    for (slang, canonical), count in pair_counts.items():
        if count < min_cooccurrence:
            continue
        confidence = round(count / (count + 2.0), 3)
        out.append(ProposedShortcut(
            slang=slang,
            canonical=canonical,
            cooccurrences=count,
            confidence=confidence,
        ))
    out.sort(key=lambda p: (-p.cooccurrences, p.slang))
    return out
