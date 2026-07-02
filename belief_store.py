"""Phase 16 — durable belief / preference store (long-horizon memory).

The memory_distiller already extracts lessons + knowledge every few hours, but
those are flat and transient. This layer holds Ultron's DURABLE model of the
user: beliefs that STRENGTHEN when reinforced by repeated evidence and DECAY
when they go stale or are contradicted — so the model deepens over weeks.

Core is pure + deterministic (no LLM): evidence in -> confidence-weighted
beliefs out. Persisted to beliefs.json (gitignored).

    consolidate(evidence)     — merge a batch of evidence into the store.
    apply_decay(now)          — age out beliefs that haven't been reinforced.
    top_beliefs(n, min_conf)  — highest-confidence beliefs (for prompt use).
    get_beliefs_block()       — a compact text block for prompt injection.
"""
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STORE_PATH = os.path.join(_BASE_DIR, "beliefs.json")

# confidence = evidence_count / (evidence_count + K). K=2 -> 1:0.33 3:0.6 10:0.83
_CONFIDENCE_K = 2.0
_BASE_CONFIDENCE = 0.34            # a single sighting
_DECAY_AFTER_SECONDS = 30 * 86400  # untouched >30d starts decaying
_DECAY_FACTOR = 0.5                # halve confidence per decay application
_CONFIDENCE_FLOOR = 0.1            # below this a belief is dropped
_NEGATIONS = {"not", "no", "never", "dislike", "dislikes", "hate", "hates",
              "doesn't", "don't", "isn't", "aren't", "won't", "avoid", "avoids"}

_lock = threading.RLock()


def _now() -> float:
    return time.time()


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _tokens(statement: str) -> List[str]:
    return [w for w in re.findall(r"[a-zA-Z']+", (statement or "").lower())]


def _content_tokens(statement: str) -> frozenset:
    """Statement tokens with negation words removed — the polarity-free core."""
    return frozenset(t for t in _tokens(statement) if t not in _NEGATIONS)


def _has_negation(statement: str) -> bool:
    return any(t in _NEGATIONS for t in _tokens(statement))


def _is_contradiction(a: str, b: str) -> bool:
    """Same content tokens but opposite polarity -> contradiction."""
    return (_content_tokens(a) == _content_tokens(b)
            and _has_negation(a) != _has_negation(b)
            and len(_content_tokens(a)) > 0)


@dataclass
class Belief:
    subject: str
    statement: str
    confidence: float
    evidence_count: int
    first_seen: float
    last_seen: float
    source: str = ""

    def key(self) -> str:
        return f"{_norm(self.subject)}::{_norm(self.statement)}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject, "statement": self.statement,
            "confidence": self.confidence, "evidence_count": self.evidence_count,
            "first_seen": self.first_seen, "last_seen": self.last_seen,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Belief":
        return cls(
            subject=d["subject"], statement=d["statement"],
            confidence=float(d.get("confidence", _BASE_CONFIDENCE)),
            evidence_count=int(d.get("evidence_count", 1)),
            first_seen=float(d.get("first_seen", _now())),
            last_seen=float(d.get("last_seen", _now())),
            source=d.get("source", ""),
        )


def _confidence_for(evidence_count: int) -> float:
    return round(min(0.99, evidence_count / (evidence_count + _CONFIDENCE_K)), 3)


# ── persistence ──────────────────────────────────────────────────────────────
def _load() -> List[Belief]:
    with _lock:
        if not os.path.exists(_STORE_PATH):
            return []
        try:
            with open(_STORE_PATH) as f:
                return [Belief.from_dict(d) for d in (json.load(f) or [])]
        except Exception:
            return []


def _save(beliefs: List[Belief]) -> None:
    with _lock:
        try:
            tmp = _STORE_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump([b.to_dict() for b in beliefs], f, indent=2)
            os.replace(tmp, _STORE_PATH)
        except Exception:
            pass


def _reset_for_test() -> None:
    with _lock:
        try:
            if os.path.exists(_STORE_PATH):
                os.remove(_STORE_PATH)
        except Exception:
            pass


# ── core ─────────────────────────────────────────────────────────────────────
def consolidate(evidence: List[Dict[str, Any]]) -> Dict[str, int]:
    """Merge a batch of evidence dicts ({subject, statement, source?}) into the
    store. Returns {added, reinforced, contradicted}."""
    summary = {"added": 0, "reinforced": 0, "contradicted": 0}
    with _lock:
        beliefs = _load()
        by_key = {b.key(): b for b in beliefs}
        now = _now()

        for ev in evidence or []:
            if not ev or not isinstance(ev, dict):
                continue
            subject = (ev.get("subject") or "").strip()
            statement = (ev.get("statement") or "").strip()
            if not subject or not statement:
                continue
            source = ev.get("source", "")
            cand = Belief(subject, statement, _BASE_CONFIDENCE, 1, now, now, source)

            # 1) exact match -> reinforce
            existing = by_key.get(cand.key())
            if existing is not None:
                existing.evidence_count += 1
                existing.confidence = _confidence_for(existing.evidence_count)
                existing.last_seen = now
                if source:
                    existing.source = source
                summary["reinforced"] += 1
                continue

            # 2) contradiction with an existing belief about the same subject
            contra = next(
                (b for b in beliefs
                 if _norm(b.subject) == _norm(subject)
                 and _is_contradiction(b.statement, statement)),
                None,
            )
            if contra is not None:
                # Weaken the old belief; the contradicting evidence enters fresh.
                contra.evidence_count = max(1, contra.evidence_count - 1)
                contra.confidence = round(contra.confidence * 0.5, 3)
                summary["contradicted"] += 1

            beliefs.append(cand)
            by_key[cand.key()] = cand
            summary["added"] += 1

        _save(beliefs)
    return summary


def apply_decay(now: Optional[float] = None) -> int:
    """Decay beliefs untouched past the window; drop those below the floor.
    Returns the number dropped."""
    n = _now() if now is None else float(now)
    with _lock:
        beliefs = _load()
        kept: List[Belief] = []
        dropped = 0
        for b in beliefs:
            if (n - b.last_seen) > _DECAY_AFTER_SECONDS:
                b.confidence = round(b.confidence * _DECAY_FACTOR, 3)
            if b.confidence < _CONFIDENCE_FLOOR:
                dropped += 1
                continue
            kept.append(b)
        _save(kept)
        return dropped


def top_beliefs(n: int = 10, min_confidence: float = 0.0) -> List[Belief]:
    beliefs = [b for b in _load() if b.confidence >= min_confidence]
    beliefs.sort(key=lambda b: (b.confidence, b.evidence_count), reverse=True)
    return beliefs[:n]


def get_beliefs_block(n: int = 8, min_confidence: float = 0.5) -> str:
    """Compact text block of durable beliefs for prompt injection."""
    top = top_beliefs(n=n, min_confidence=min_confidence)
    if not top:
        return ""
    lines = [f"- {b.subject}: {b.statement} (confidence {b.confidence:.0%})"
             for b in top]
    return "What I durably believe about the user:\n" + "\n".join(lines)


def all_beliefs() -> List[Belief]:
    return _load()
