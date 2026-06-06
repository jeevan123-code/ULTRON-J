"""Delivery Manager.

Takes a ResearchReport (wrapped in a DeliveryEnvelope with routing flags) and
fans it out to:
  - voice_engine (spoken brief, FOCUSED mood by default)
  - a structured card payload returned to the caller for UI rendering

Voice failures are caught and logged so the card still reaches the caller.
"""
from typing import Any, Dict, Optional

from research_types import DeliveryEnvelope, ResearchReport
from source_credibility import tier_for_url


def _speak(text: str) -> None:
    """Indirection so tests can patch without importing voice_engine."""
    from voice_engine import tts
    tts(text, mood="FOCUSED")


def build_card_payload(report: ResearchReport) -> Dict[str, Any]:
    """Return a UI-friendly JSON-able dict for the visual card."""
    sources_out = []
    for s in report.sources:
        url = s.get("url", "")
        sources_out.append({
            "n": s.get("n"),
            "title": s.get("title", url),
            "url": url,
            "tier": tier_for_url(url).value,
        })
    return {
        "query": report.query,
        "bullets": list(report.card_bullets),
        "sources": sources_out,
        "contradictions": list(report.contradictions),
        "ms": report.ms,
    }


def deliver(envelope: DeliveryEnvelope) -> Dict[str, Any]:
    """Execute the envelope's routing flags and report what actually happened."""
    spoken = False
    card_payload: Optional[Dict[str, Any]] = None

    if envelope.route_voice:
        try:
            _speak(envelope.report.spoken_brief)
            spoken = True
        except Exception as e:
            try:
                with open("ultron_log.txt", "a") as f:
                    f.write(f"[phase2a][voice_error] {e!r}\n")
            except Exception:
                pass

    if envelope.route_card:
        card_payload = build_card_payload(envelope.report)

    return {"spoken": spoken, "card": card_payload}
