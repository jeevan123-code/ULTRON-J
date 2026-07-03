"""Phase 22 — predictive intervention (Tier 3).

predictive_monitor already forecasts trouble (memory climbing, disk filling,
provider failures rising) and ALERTS. Phase 22 upgrades alerting to ACTING: each
predicted anomaly becomes a parked remediation GOAL via goal_author, so Ultron
proposes to fix the problem before it lands ("disk will fill in ~2h — investigate
and clear caches?") rather than only warning.

Remediation goals are research/investigate category (GREEN) — any destructive
step in their eventual execution is still gated by the Phase 17 capability
policy. Dedup (goal_author's 24h cooldown per trigger:subject) stops a standing
anomaly from spamming proposals.
"""
from typing import Any, Dict, List, Optional

from goal_author_types import GoalProposal


def remediation_for(anomaly: Dict[str, Any]) -> Optional[GoalProposal]:
    """Map one anomaly finding ({key, severity, summary, action}) to a
    remediation proposal. Returns None if the anomaly is malformed."""
    if not isinstance(anomaly, dict):
        return None
    key = (anomaly.get("key") or "").strip()
    summary = (anomaly.get("summary") or "").strip()
    if not key or not summary:
        return None
    action = (anomaly.get("action") or "").strip()
    severity = anomaly.get("severity", "medium")
    desc = summary + (f" Suggested remediation: {action}" if action else "")
    return GoalProposal(
        title=f"Preempt predicted issue: {key}",
        description=desc,
        rationale=summary,
        trigger="predictive",
        subject=key,
        priority="high" if severity == "high" else "medium",
        confidence=0.7 if severity == "high" else 0.55,
        category="research",
    )


def intervene(anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn a list of anomalies into parked/created remediation goals."""
    proposals = [p for p in (remediation_for(a) for a in (anomalies or [])) if p]
    if not proposals:
        return {"proposed": 0, "dropped_red": 0, "deduped": 0,
                "created": 0, "parked": 0}
    import goal_author
    return goal_author.submit_proposals(proposals)


def run(n: int = 10) -> Dict[str, Any]:
    """Read recent anomalies from predictive_monitor and intervene."""
    try:
        import predictive_monitor
        anomalies = predictive_monitor.get_anomaly_log(n=n)
    except Exception:
        anomalies = []
    return intervene(anomalies)
