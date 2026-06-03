"""
loop_supervisor.py — Phase 4.1/4.2 single point of control for every
background daemon Ultron-J launches at boot.

Why this exists:
  * Before Phase 4 there were ~13 always-on threads kicked off
    directly from app.py main / ultimate_routes.start_ultimate_loops,
    each with its own hard-coded interval. Half of them ran on empty
    input (evolution / proactive / skill_learner -- nothing for them
    to act on until goals exist). The predictive monitor rewrote
    predictive_metrics.json every 60s, which along with the episodic
    memory churn drove `mem_rising` anomalies and pinned health_score
    to 17.
  * This module reads `config.LOOPS` and offers three primitives every
    start_* function in the repo calls:
        loop_enabled(name)       -> bool   ("should I start at all?")
        loop_interval_s(name, default) -> float
        should_skip_heavy_tick() -> bool   ("am I above the memory
                                            backpressure threshold?")
  * The contract is intentionally tiny so adopting it in each existing
    start_* doesn't require an architectural rewrite -- just a one-line
    guard at the top of the function.

Env-var overrides (no code edit needed to retune):
  LOOPS_<NAME>_ENABLED=0|1     -- override config.LOOPS[name]["enabled"]
  LOOPS_<NAME>_INTERVAL_S=<n>  -- override interval in seconds
                                  (where <NAME> is uppercased loop key,
                                  e.g. LOOPS_DISTILLER_INTERVAL_S=900)

Backpressure:
  config.MEM_BACKPRESSURE_PCT (default 70%, ULTRON_MEM_BACKPRESSURE_PCT
  env var override). When system memory usage exceeds this, heavy
  loops should skip the current tick. Lightweight loops
  (system_monitor heartbeat, plugin_watcher) are intentionally NOT
  expected to consult this -- backpressure is the heavy loops' choice.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

import config as _cfg


# ─── Config lookup ────────────────────────────────────────────────────────────

def _env_override_bool(name: str) -> Optional[bool]:
    raw = os.environ.get(f"LOOPS_{name.upper()}_ENABLED")
    if raw is None:
        return None
    return raw.strip() not in ("0", "false", "False", "")


def _env_override_interval(name: str) -> Optional[float]:
    raw = os.environ.get(f"LOOPS_{name.upper()}_INTERVAL_S")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def loop_enabled(name: str) -> bool:
    """True if the loop should start. Env var beats config.LOOPS.
    Unknown names default to True (don't break loops added later that
    haven't been registered yet)."""
    override = _env_override_bool(name)
    if override is not None:
        return override
    spec = _cfg.LOOPS.get(name)
    if spec is None:
        return True
    return bool(spec.get("enabled", True))


def loop_interval_s(name: str, default: float) -> float:
    """Configured interval for this loop, or the caller's default."""
    override = _env_override_interval(name)
    if override is not None:
        return override
    spec = _cfg.LOOPS.get(name)
    if spec is None:
        return default
    return float(spec.get("interval_s", default))


# ─── Memory backpressure ──────────────────────────────────────────────────────

def current_mem_pct() -> float:
    """Return system memory used %, or 0.0 if psutil unavailable. 0.0
    is a deliberate "no signal -> never skip" -- we'd rather a tick
    runs than be silently throttled by a missing dep."""
    if not _PSUTIL:
        return 0.0
    try:
        return float(psutil.virtual_memory().percent)
    except Exception:
        return 0.0


def should_skip_heavy_tick() -> bool:
    """True if heavy loops should skip this tick. Threshold from
    config.MEM_BACKPRESSURE_PCT. Designed to be called once at the top
    of each iteration of a heavy loop."""
    return current_mem_pct() > _cfg.MEM_BACKPRESSURE_PCT


# ─── Reporting (for /loop/status & ad-hoc debugging) ──────────────────────────

def snapshot() -> dict:
    """Return the effective state of every registered loop -- what
    config.LOOPS says, what the env-var overrides resolve to, current
    memory pct, and the backpressure threshold."""
    state = {}
    for name in _cfg.LOOPS:
        spec = _cfg.LOOPS[name]
        state[name] = {
            "configured_enabled":  spec.get("enabled"),
            "configured_interval": spec.get("interval_s"),
            "effective_enabled":   loop_enabled(name),
            "effective_interval":  loop_interval_s(name, spec.get("interval_s", 0)),
        }
    return {
        "loops":                state,
        "mem_pct":              current_mem_pct(),
        "backpressure_pct":     _cfg.MEM_BACKPRESSURE_PCT,
        "backpressure_active":  should_skip_heavy_tick(),
    }
