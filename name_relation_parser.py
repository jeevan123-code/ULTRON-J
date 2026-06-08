"""Name + relation parser for the stranger-enrollment voice flow.

Deterministic keyword matching. No LLM. Returns ParsedNameRelation with
name=None when the utterance is a skip or doesn't contain an enrollment.
"""
import re
from typing import Optional

from person_types import Relation
from voice_id_types import ParsedNameRelation


_SKIP_PHRASES = (
    "skip it", "skip", "not now", "no thanks", "no thank you",
    "ignore it", "ignore that", "forget it", "i don't want",
    "i dont want", "nope", "no",
)


_RELATION_KEYWORDS = {
    "brother": Relation.FAMILY,
    "sister": Relation.FAMILY,
    "dad": Relation.FAMILY,
    "father": Relation.FAMILY,
    "mom": Relation.FAMILY,
    "mum": Relation.FAMILY,
    "mother": Relation.FAMILY,
    "parent": Relation.FAMILY,
    "uncle": Relation.FAMILY,
    "aunt": Relation.FAMILY,
    "cousin": Relation.FAMILY,
    "nephew": Relation.FAMILY,
    "niece": Relation.FAMILY,
    "son": Relation.FAMILY,
    "daughter": Relation.FAMILY,
    "wife": Relation.FAMILY,
    "husband": Relation.FAMILY,
    "spouse": Relation.FAMILY,
    "friend": Relation.FRIEND,
    "buddy": Relation.FRIEND,
    "mate": Relation.FRIEND,
    "pal": Relation.FRIEND,
    "roommate": Relation.FRIEND,
    "boss": Relation.PROFESSIONAL,
    "manager": Relation.PROFESSIONAL,
    "colleague": Relation.PROFESSIONAL,
    "coworker": Relation.PROFESSIONAL,
    "client": Relation.PROFESSIONAL,
    "customer": Relation.PROFESSIONAL,
    "lawyer": Relation.PROFESSIONAL,
    "doctor": Relation.PROFESSIONAL,
}


_NAME_PATTERNS = [
    re.compile(r"\bthat'?s\s+my\s+(?:brother|sister|dad|father|mom|mother|uncle|aunt|cousin|son|daughter|friend|buddy|boss|manager|colleague|coworker|client|wife|husband)\s+([a-z][a-z]*)\b", re.IGNORECASE),
    re.compile(r"\bit'?s\s+my\s+(?:brother|sister|dad|father|mom|mother|uncle|aunt|cousin|son|daughter|friend|buddy|boss|manager|colleague|coworker|client|wife|husband)\s+([a-z][a-z]*)\b", re.IGNORECASE),
    re.compile(r"\bthis\s+is\s+([a-z][a-z]*)", re.IGNORECASE),
    re.compile(r"\bthat'?s\s+([a-z][a-z]*)", re.IGNORECASE),
    re.compile(r"\bthat\s+is\s+([a-z][a-z]*)", re.IGNORECASE),
    re.compile(r"\bit'?s\s+([a-z][a-z]*)", re.IGNORECASE),
    re.compile(r"(?:his|her|their)\s+name\s+is\s+([a-z][a-z]*)", re.IGNORECASE),
]


def _detect_relation(text_lc: str) -> Relation:
    for word, rel in _RELATION_KEYWORDS.items():
        if re.search(rf"\b{word}\b", text_lc):
            return rel
    return Relation.STRANGER


def _detect_name(text: str) -> Optional[str]:
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip().capitalize()
    return None


def parse_name_relation(text: str) -> ParsedNameRelation:
    """Parse 'That's Ravi, my brother' -> ParsedNameRelation(name='Ravi', relation=FAMILY)."""
    if not text or not text.strip():
        return ParsedNameRelation(name=None, relation=Relation.STRANGER)

    lc = text.strip().lower()
    if any(skip in lc for skip in _SKIP_PHRASES):
        return ParsedNameRelation(name=None, relation=Relation.STRANGER)

    name = _detect_name(text)
    relation = _detect_relation(lc)
    return ParsedNameRelation(name=name, relation=relation)
