"""Verified-fact storage for cross-session recall.

ULTRON's existing vector_store.py already caches whole research result dicts.
This module operates one level finer: it stores individual atomic CitedFacts
above a confidence threshold so unrelated future queries can recall single
verified claims without paying the full research cost again.

Public API:
    store_verified_facts(report, min_confidence=0.6) -> int
    recall_facts(topic, k=5) -> List[Dict]

Both gracefully degrade when the vector store is unavailable.
"""
from typing import Any, Dict, List

from research_types import ResearchReport


def _get_vector_store():
    """Indirection so tests can patch without importing the real vector store."""
    import vector_store
    return vector_store


def store_verified_facts(report: ResearchReport, min_confidence: float = 0.6) -> int:
    """Persist each CitedFact above min_confidence into the vector store.

    Returns the count actually stored.
    """
    vs = _get_vector_store()
    stored = 0
    for fact in report.facts:
        if fact.confidence < min_confidence:
            continue
        metadata = {
            "query": report.query,
            "confidence": fact.confidence,
            "source_urls": ",".join(fact.source_urls),
            "tiers": ",".join(t.value for t in fact.tiers),
        }
        try:
            vs.remember(text=fact.text, kind="research_fact", metadata=metadata)
            stored += 1
        except Exception:
            try:
                with open("ultron_log.txt", "a") as f:
                    f.write(f"[phase2a][fact_store_error] could not store fact: {fact.text[:80]}\n")
            except Exception:
                pass
    return stored


def recall_facts(topic: str, k: int = 5) -> List[Dict[str, Any]]:
    """Recall up to k verified facts similar to the topic. Returns [] on failure."""
    try:
        vs = _get_vector_store()
        return list(vs.recall(topic, n=k, kind="research_fact"))
    except Exception:
        return []
