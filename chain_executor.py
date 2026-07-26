"""Phase 8 multi-step plan executor.

Runs an `ExecutionPlan` whose `steps` contain a chain of different action
types — `research`, `takeover`, `scenario`, `alert`, `announce`,
`briefing` — and dispatches each to its existing phase executor.

Two features that make this more than a loop:

1. **Inter-step references.** A step's args can use `{{prev.<key>}}`
   placeholders to pull values from the previous step's result. E.g., a
   research step returns `summary="…"`, the next alert step can use
   `{"message": "Research: {{prev.summary}}"}` and the rendered text
   includes the research summary.

2. **Failure policy.** By default the chain stops at the first failure.
   A step can opt out with `continue_on_failure: True` (mirrors the
   defensive style elsewhere in the codebase).

Every dispatcher is a small module-level indirection so tests can stub
without touching the underlying phase modules. Exceptions in any step
are caught and recorded as `{"ok": False, "error": "..."}`; the chain
never propagates exceptions to its caller.
"""
import re
from typing import Any, Dict, List

from intent_types import ExecutionPlan


_PLACEHOLDER = re.compile(r"\{\{prev\.([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


# ---- per-action dispatchers (module-level seams for tests) ----

def _dispatch_research(step: Dict[str, Any]) -> Dict[str, Any]:
    from phase2_executor import execute as _exec
    plan = ExecutionPlan(steps=[step], pre_checks=[], rationale="chain step")
    return _exec(plan)


def _dispatch_takeover(step: Dict[str, Any]) -> Dict[str, Any]:
    from takeover_executor import execute as _exec
    plan = ExecutionPlan(steps=[step], pre_checks=[], rationale="chain step")
    return _exec(plan)


def _dispatch_alert(message: str, priority: str) -> Dict[str, Any]:
    import mobile_bridge
    mobile_bridge.alert(message, priority=priority)
    return {"sent": True, "message": message, "priority": priority}


def _dispatch_announce(text: str):
    from voice_engine import tts
    return tts(text, mood="FOCUSED")


def _dispatch_scenario(name: str) -> Dict[str, Any]:
    import multi_device_coordinator as mdc
    for sc in mdc._snapshot_for_test():
        if sc.name == name:
            return mdc.run(sc)
    return {}


def _dispatch_briefing(channels: List[str]) -> Dict[str, Any]:
    import time as _t
    import briefing_builder, briefing_delivery
    text = briefing_builder.compose(now=_t.time())
    return briefing_delivery.deliver(text, channels)


def _dispatch_look() -> Dict[str, Any]:
    """Phase 9: grab a webcam frame and distil it via vision_perception."""
    import vision_capture
    import vision_perception
    frame = vision_capture.get_latest_frame()
    if frame is None:
        return {"ok": False, "reason": "no_frame"}
    obs = vision_perception.observe(frame)
    if obs is None:
        return {"ok": False, "reason": "no_observation"}
    return {"ok": True, **obs.to_dict()}


# ---- helpers ----

def _interpolate(args: Dict[str, Any], prev: Dict[str, Any]) -> Dict[str, Any]:
    """Replace {{prev.<key>}} placeholders in string args with prev[key]."""
    out: Dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str):
            def _sub(match):
                key = match.group(1)
                if isinstance(prev, dict) and key in prev:
                    return str(prev[key])
                return match.group(0)  # leave placeholder if no key
            out[k] = _PLACEHOLDER.sub(_sub, v)
        else:
            out[k] = v
    return out


def _safe_log(msg: str) -> None:
    try:
        with open("ultron_log.txt", "a") as f:
            f.write(f"[phase8][chain] {msg}\n")
    except Exception:
        pass


def _run_one(step: Dict[str, Any], prev_result: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a single step. Returns a uniform {ok, action, result|error} dict."""
    action = step.get("action")
    args = _interpolate(step.get("args", {}) or {}, prev_result)
    step_with_args = {**step, "args": args}

    try:
        if action == "research":
            result = _dispatch_research(step_with_args)
            ok = bool(result.get("executed"))
            return {"ok": ok, "action": action, "result": result}

        if action == "takeover":
            result = _dispatch_takeover(step_with_args)
            ok = bool(result.get("executed"))
            return {"ok": ok, "action": action, "result": result}

        if action == "alert":
            message = args.get("message", "")
            priority = args.get("priority", "normal")
            result = _dispatch_alert(message, priority)
            return {"ok": bool(result.get("sent")), "action": action, "result": result}

        if action == "announce":
            text = args.get("text", "")
            audio, provider = _dispatch_announce(text)
            return {"ok": True, "action": action,
                    "result": {"provider": provider, "bytes": len(audio or b"")}}

        if action == "scenario":
            name = args.get("name", "")
            result = _dispatch_scenario(name)
            return {"ok": bool(result), "action": action, "result": result}

        if action == "briefing":
            channels = args.get("channels", ["telegram"])
            result = _dispatch_briefing(channels)
            return {"ok": bool(result), "action": action, "result": result}

        if action == "look":
            result = _dispatch_look()
            ok = bool(result.get("ok"))
            if not ok:
                return {"ok": False, "action": action,
                        "error": result.get("reason", "look_failed")}
            # Surface the observation directly as `result` so
            # {{prev.faces}} / {{prev.person_present}} resolve in next step
            return {"ok": True, "action": action, "result": result}

        return {"ok": False, "action": action,
                "error": f"unknown action {action!r}"}

    except Exception as e:
        _safe_log(f"step {action!r} raised: {e!r}")
        return {"ok": False, "action": action, "error": repr(e)}


def _should_skip(step: Dict[str, Any], prev_ran: bool, prev_ok: bool) -> bool:
    """Phase 11 conditional gating.

    `if_prev_ok: True`   — run only when the prior executed step succeeded.
                           For the very first step (no prev yet) this is
                           vacuously satisfied, so the step runs.
    `if_prev_failed: True` — run only when the prior executed step failed.
                             For the first step (no prev) this is NOT
                             satisfied, so the step is skipped.

    Skipped steps appear in the results list with `{"skipped": True}` so
    the chain is fully auditable. Skipped steps do not reset `prev_result`
    nor flip `prev_ok` — they're neutral for downstream conditions.
    """
    if step.get("if_prev_ok"):
        if prev_ran and not prev_ok:
            return True
    if step.get("if_prev_failed"):
        if (not prev_ran) or prev_ok:
            return True
    return False


def execute_chain(plan: ExecutionPlan,
                  strict_validation: bool = False) -> List[Dict[str, Any]]:
    """Run every step of `plan.steps` in order; return per-step results.

    Stops on the first failed step unless that step set
    `continue_on_failure: True`. Each step's `prev_result` is the
    `result` dict of the previous successful step (used for `{{prev.X}}`
    interpolation).

    Phase 11: steps may carry `if_prev_ok` / `if_prev_failed` flags. When
    the condition is not met the step is recorded as `{"skipped": True}`
    and the chain proceeds.

    Phase 13: `strict_validation=True` runs `plan_validator.validate(plan)`
    before any step executes. If any issue has severity `error`, no step
    runs and a single result is returned with
    `{ok: False, skipped: True, reason: "validation_failed",
      validation_issues: [...]}`. Warnings do NOT block execution.
    """
    if strict_validation:
        try:
            import plan_validator
            issues = plan_validator.validate(plan)
            errors = [i for i in issues
                      if i.severity == plan_validator.SEVERITY_ERROR]
            if errors:
                return [{
                    "ok": False,
                    "skipped": True,
                    "reason": "validation_failed",
                    "validation_issues": [i.to_dict() for i in errors],
                }]
        except Exception as e:
            _safe_log(f"strict validation crashed: {e!r}")
            # Fall through and run the chain — validation must never make
            # the system *less* reliable than running unchecked.

    results: List[Dict[str, Any]] = []
    prev_result: Dict[str, Any] = {}
    prev_ran = False
    prev_ok = False

    for step in plan.steps or []:
        if _should_skip(step, prev_ran, prev_ok):
            results.append({
                "ok": False,
                "skipped": True,
                "action": step.get("action"),
                "reason": "condition_not_met",
            })
            # Don't touch prev_result / prev_ran / prev_ok — neutral.
            continue

        outcome = _run_one(step, prev_result)
        results.append(outcome)
        prev_ran = True

        if outcome.get("ok"):
            r = outcome.get("result")
            prev_result = r if isinstance(r, dict) else {}
            prev_ok = True
            continue

        # failed
        prev_ok = False
        if step.get("continue_on_failure"):
            prev_result = {}
            continue
        break

    return results


# ── Phase 21: multi-agent fan-out ────────────────────────────────────────────
def execute_parallel(agents, max_workers: int = 4,
                     per_agent_timeout: float = 60.0) -> Dict[str, Any]:
    """Run several INDEPENDENT plans as sub-agents and merge their results.

    `execute_chain` runs one plan sequentially; this is the seam where the
    Phase 21 swarm coordinator hangs off it. `agents` is a list of
    `swarm_coordinator.SubAgent(name, role, plan)`.

    ULTRON_PHASE21_ENABLED controls PARALLELISM, not existence: with the flag
    off every plan still runs, just one at a time and in order. A fan-out that
    silently did nothing when disabled would recreate the orphan it fixes.

    Failure isolation holds on both paths — one agent raising, failing or
    timing out never stops the others.
    """
    import os
    import swarm_coordinator

    if not agents:
        return swarm_coordinator.summarize({})

    if os.environ.get("ULTRON_PHASE21_ENABLED", "0") == "1":
        return swarm_coordinator.run_swarm(
            agents, max_workers=max_workers,
            per_agent_timeout=per_agent_timeout)

    # Sequential fallback — same merge logic, so callers see one shape.
    out: Dict[str, Dict[str, Any]] = {}
    for agent in agents:
        entry: Dict[str, Any] = {"role": agent.role}
        try:
            results = execute_chain(agent.plan)
            entry["results"] = results
            entry["ok"] = swarm_coordinator._results_ok(results)
        except Exception as e:
            entry["ok"] = False
            entry["error"] = repr(e)
        out[agent.name] = entry
    return swarm_coordinator.summarize(out)
