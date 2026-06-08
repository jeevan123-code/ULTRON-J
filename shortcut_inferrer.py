"""Shortcut Inferrer — parse 'by X I mean Y' utterances + resolve known
shortcuts inside arbitrary text.

Public API:
    parse_teach_utterance(text) -> Optional[Tuple[str, str]]
    resolve_in_text(text) -> Dict[str, str]   # normalised_term -> canonical
"""
import re
from typing import Dict, Optional, Tuple

import shortcut_registry


_TEACH_PATTERNS = (
    # by "X" I mean Y / by 'X' I mean Y / by X I mean Y
    re.compile(
        r"\bby\s+(?:['\"]([^'\"]+)['\"]|([\w\-\s]+?))\s+i\s+mean\s+([\w\-]+)",
        re.IGNORECASE,
    ),
    # when I say "X", I mean Y / when I say X I mean Y
    re.compile(
        r"\bwhen\s+i\s+say\s+(?:['\"]([^'\"]+)['\"]|([\w\-\s]+?))[,\s]+i\s+mean\s+([\w\-]+)",
        re.IGNORECASE,
    ),
    # "X" means Y / 'X' means Y
    re.compile(
        r"['\"]([^'\"]+)['\"]\s+means\s+([\w\-]+)",
        re.IGNORECASE,
    ),
)


def parse_teach_utterance(text: str) -> Optional[Tuple[str, str]]:
    """Return (term, canonical) if `text` is an explicit teach utterance.

    Preserves the original casing of both fields. Returns None on any
    text that doesn't match a teach pattern or whose captured term is empty.
    """
    if not text or not text.strip():
        return None

    for pat in _TEACH_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 3:
            quoted, unquoted, canonical = groups
            term = quoted if quoted is not None else (unquoted or "")
        else:
            term, canonical = groups
        term = (term or "").strip()
        canonical = (canonical or "").strip().rstrip(".,!?;:")
        if not term or not canonical:
            return None
        return term, canonical
    return None


def resolve_in_text(text: str) -> Dict[str, str]:
    """Return {normalised_term: canonical} for every known shortcut that
    appears (whole-word, case-insensitive) inside `text`."""
    if not text or not text.strip():
        return {}

    lc = text.lower()
    out: Dict[str, str] = {}
    for s in shortcut_registry.list_all():
        norm_term = s.term.strip().lower()
        if not norm_term:
            continue
        pat = re.compile(rf"(?<![\w]){re.escape(norm_term)}(?![\w])", re.IGNORECASE)
        if pat.search(lc):
            out[norm_term] = s.canonical
    return out
