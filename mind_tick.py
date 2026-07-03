"""Phase 7 unified mind tick.

ULTRON's prior phases each ran in isolation: Phase 6 polled the world,
Phase 6 scheduled briefings, Phase 3c watched for improvement patterns,
Phase 4 matched scenarios. Nothing tied them together into a single
"thinking" cycle. `mind_tick.tick()` is that unifier.

One tick:
  1. Asks `briefing_scheduler` if any cron schedules are due → dispatches them.
  2. Asks `worldfeed_store` for very-high-score events not yet alerted →
     pushes a Telegram alert.
  3. Asks `improvement_suggester` over the recent `action_log` → if a
     suggestion fires AND no proactive offer is pending, parks it via
     `proactive_offer.offer_takeover_suggestion` so a HANDS_ON reply later
     can trigger the takeover.

Every stage is wrapped in try/except. One stage's failure never aborts
the next.

Flag-gated by `ULTRON_PHASE7_ENABLED`. The autonomous_loop calls
`tick()` once per its iteration when the flag is on.
"""
import threading
import time
from typing import Any, Dict, List, Set


# State that must persist between ticks
_lock = threading.RLock()
_alerted_titles: Set[str] = set()
_HIGH_SCORE_THRESHOLD = 0.85


def _now() -> float:
    return time.time()


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase7][mind_tick] {msg}\n")
    except Exception:
        pass


def _reset_for_test() -> None:
    with _lock:
        _alerted_titles.clear()


def _telegram_alert(text: str) -> Dict[str, Any]:
    """Indirection so tests can stub. Uses mobile_bridge.alert if available."""
    try:
        import mobile_bridge
        mobile_bridge.alert(text, priority="high")
        return {"ok": True}
    except Exception as e:
        _safe_log(f"telegram alert failed: {e!r}")
        return {"ok": False, "error": repr(e)}


def _stage_briefings(now: float, summary: Dict[str, Any]) -> None:
    try:
        import briefing_scheduler
        results = briefing_scheduler.tick(now=now, window_seconds=60.0)
        summary["briefings_dispatched"] = len(results or {})
    except Exception as e:
        _safe_log(f"briefing stage failed: {e!r}")
        summary["scheduler_error"] = repr(e)


def _stage_world_alerts(now: float, summary: Dict[str, Any]) -> None:
    try:
        import worldfeed_store
        # Look at last hour of events, sorted by score desc
        events = worldfeed_store.recent(now=now, within_seconds=3600, top_n=5)
        alerts_sent = 0
        with _lock:
            for ev in events or []:
                title = getattr(ev, "title", "")
                score = getattr(ev, "score", 0.0)
                if score < _HIGH_SCORE_THRESHOLD:
                    continue
                if not title or title in _alerted_titles:
                    continue
                # Park before sending so a slow telegram call doesn't
                # cause a re-alert race on the next tick.
                _alerted_titles.add(title)
                res = _telegram_alert(f"World pulse: {title}")
                if res.get("ok"):
                    alerts_sent += 1
        summary["world_alerts"] = alerts_sent
    except Exception as e:
        _safe_log(f"world alert stage failed: {e!r}")
        summary["world_alert_error"] = repr(e)


def _stage_improvement(now: float, summary: Dict[str, Any]) -> None:
    try:
        import action_log
        import improvement_suggester
        import proactive_offer
        from intent_types import ExecutionPlan

        # Skip silently if another offer is already pending — never double-park.
        if proactive_offer.peek_pending_offer() is not None:
            summary["improvement_offers"] = 0
            return

        events = action_log.recent(now=now, within_seconds=600)
        suggestions = improvement_suggester.analyze(events)
        offers = 0
        for s in suggestions:
            # Each suggestion turns into a takeover plan whose first step
            # is the template name. The actual fleshed-out plan is built
            # later by whatever script generator we eventually wire up.
            plan = ExecutionPlan(
                steps=[{"action": "takeover", "args": {"template": s.template}}],
                pre_checks=[], rationale=s.summary,
            )
            try:
                proactive_offer.offer_takeover_suggestion(s, plan)
                offers += 1
                break  # park one, let the user respond before piling more
            except Exception as e:
                _safe_log(f"offer parking failed: {e!r}")
        summary["improvement_offers"] = offers
    except Exception as e:
        _safe_log(f"improvement stage failed: {e!r}")
        summary["improvement_error"] = repr(e)


def _stage_shortcuts(now: float, summary: Dict[str, Any]) -> None:
    """Phase 5g: register any newly-confident implicit shortcuts inferred from
    observed utterances. Gated by ULTRON_PHASE5G_ENABLED so it stays off unless
    the implicit learner is explicitly enabled."""
    import os
    if os.environ.get("ULTRON_PHASE5G_ENABLED", "0") != "1":
        summary["shortcuts_learned"] = 0
        return
    try:
        import phase5g_implicit_hook
        written = phase5g_implicit_hook.tick()
        summary["shortcuts_learned"] = len(written)
    except Exception as e:
        _safe_log(f"shortcut stage failed: {e!r}")
        summary["shortcut_error"] = repr(e)


def _stage_beliefs(now: float, summary: Dict[str, Any]) -> None:
    """Phase 16: consolidate new personal facts into the durable belief store
    (reinforce/decay). Gated by ULTRON_PHASE16_ENABLED."""
    import os
    if os.environ.get("ULTRON_PHASE16_ENABLED", "0") != "1":
        summary["beliefs_consolidated"] = 0
        return
    try:
        import belief_consolidation
        r = belief_consolidation.run(now=now)
        summary["beliefs_consolidated"] = r.get("added", 0) + r.get("reinforced", 0)
    except Exception as e:
        _safe_log(f"belief stage failed: {e!r}")
        summary["belief_error"] = repr(e)


def _stage_predictive(now: float, summary: Dict[str, Any]) -> None:
    """Phase 22: turn predicted anomalies into parked remediation goals.
    Gated by ULTRON_PHASE22_ENABLED."""
    import os
    if os.environ.get("ULTRON_PHASE22_ENABLED", "0") != "1":
        summary["predictive_interventions"] = 0
        return
    try:
        import predictive_intervention
        r = predictive_intervention.run()
        summary["predictive_interventions"] = r.get("created", 0) + r.get("parked", 0)
    except Exception as e:
        _safe_log(f"predictive stage failed: {e!r}")
        summary["predictive_error"] = repr(e)


def tick(now: float = None) -> Dict[str, Any]:
    """Run one unified mind tick across every Phase 3c/4/6 surface."""
    n = _now() if now is None else float(now)
    summary: Dict[str, Any] = {
        "ts": n,
        "briefings_dispatched": 0,
        "world_alerts": 0,
        "improvement_offers": 0,
        "shortcuts_learned": 0,
        "beliefs_consolidated": 0,
        "predictive_interventions": 0,
    }
    _stage_briefings(n, summary)
    _stage_world_alerts(n, summary)
    _stage_improvement(n, summary)
    _stage_shortcuts(n, summary)
    _stage_beliefs(n, summary)
    _stage_predictive(n, summary)
    return summary
