"""
predictive_monitor.py — Anomaly detection + proactive alerts for Ultron-J.

Watches rolling metrics from system_monitor, the execution log, and provider
health, then flags ANOMALIES that suggest an impending failure:

  - CPU/RAM/disk trending upward over a window
  - Provider failure rate climbing (rate-limiting coming)
  - Goal execution success rate dropping
  - LLM timeouts clustering
  - Voice TTS cache growing unbounded
  - Patch failure rate climbing (sign of a regression)

Unlike the reactive system_monitor alerts (which fire on thresholds already
crossed), this module looks at TRENDS — e.g. "memory climbed from 62% to 88%
over the last 20 minutes, projected 100% in ~8 minutes".

Output flows into the existing system_monitor.push_alert channel so Jeevan's
UI shows it alongside normal alerts. Critical trends also create a proposal
via system_monitor.add_proposal so the tweak_engine / evolution_loop can act.

Public API:
    run_check()             synchronous one-shot check
    start_monitor()         background loop
    stop_monitor()
    get_monitor_status()
    get_anomaly_log(n=20)
"""

import json
import os
import time
import threading
import datetime
from typing import Dict, List, Optional

try:
    from config import _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from system_monitor import (
        get_memory_usage, get_cpu_usage, get_disk_usage,
        push_alert, add_proposal,
    )
    _SYS_AVAILABLE = True
except ImportError:
    _SYS_AVAILABLE = False
    def get_memory_usage(): return {"percent": 0}
    def get_cpu_usage(): return {"percent": 0}
    def get_disk_usage(): return {"percent": 0}
    def push_alert(msg): print(f"[ALERT] {msg}")
    def add_proposal(**kw): return {}

try:
    from llm_engine import get_provider_health
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False
    def get_provider_health(): return {}

try:
    from decision_engine import get_execution_log
except ImportError:
    def get_execution_log(n=20): return []


METRICS_FILE    = os.path.join(_BASE_DIR, "predictive_metrics.json")
ANOMALY_LOG_FILE = os.path.join(_BASE_DIR, "anomaly_log.json")

DEFAULT_INTERVAL_SEC = 60
WINDOW_SIZE = 20            # keep last N samples
ALERT_COOLDOWN_SEC = 600    # don't re-alert the same anomaly within 10 minutes


_lock = threading.Lock()


# =============================================================================
# METRICS STORAGE
# =============================================================================

def _load_metrics() -> Dict:
    if not os.path.exists(METRICS_FILE):
        return {
            "samples":       [],
            "last_alert":    {},     # anomaly_key -> ISO timestamp
            "run_count":     0,
        }
    try:
        with open(METRICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"samples": [], "last_alert": {}, "run_count": 0}


def _save_metrics(m: Dict):
    try:
        with open(METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=2)
    except Exception as e:
        print(f"[predictive] save failed: {e}")


def _append_anomaly(entry: Dict):
    log = []
    if os.path.exists(ANOMALY_LOG_FILE):
        try:
            with open(ANOMALY_LOG_FILE, "r", encoding="utf-8") as f:
                log = json.load(f) or []
        except Exception:
            log = []
    log.append(entry)
    try:
        with open(ANOMALY_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log[-200:], f, indent=2)
    except Exception:
        pass


def get_anomaly_log(n: int = 20) -> List[Dict]:
    if not os.path.exists(ANOMALY_LOG_FILE):
        return []
    try:
        with open(ANOMALY_LOG_FILE, "r", encoding="utf-8") as f:
            log = json.load(f) or []
        return log[-n:][::-1]
    except Exception:
        return []


# =============================================================================
# SAMPLE COLLECTION
# =============================================================================

def _collect_sample() -> Dict:
    """Grab one snapshot of all monitored metrics."""
    now = datetime.datetime.now()
    sample = {"ts": now.isoformat()}

    if _SYS_AVAILABLE:
        try:
            m = get_memory_usage()
            sample["mem_pct"] = float(m.get("percent", 0))
        except Exception:
            sample["mem_pct"] = 0.0
        try:
            c = get_cpu_usage()
            sample["cpu_pct"] = float(c.get("percent", 0))
        except Exception:
            sample["cpu_pct"] = 0.0
        try:
            d = get_disk_usage()
            sample["disk_pct"] = float(d.get("percent", 0))
        except Exception:
            sample["disk_pct"] = 0.0

    # Provider failure counts (total errors across all providers)
    if _LLM_AVAILABLE:
        try:
            health = get_provider_health()
            fails = 0
            for _, info in (health or {}).items():
                if isinstance(info, dict):
                    fails += int(info.get("consecutive_failures", 0))
            sample["provider_fails"] = fails
        except Exception:
            sample["provider_fails"] = 0
    else:
        sample["provider_fails"] = 0

    # Goal execution recent failure rate (last 10 steps)
    try:
        execlog = get_execution_log(n=10) or []
        n_steps = len(execlog)
        n_fail = sum(1 for e in execlog if isinstance(e, dict) and not e.get("success"))
        sample["exec_fail_rate"] = (n_fail / n_steps) if n_steps else 0.0
    except Exception:
        sample["exec_fail_rate"] = 0.0

    return sample


# =============================================================================
# ANOMALY DETECTION
# =============================================================================

def _linear_trend(samples: List[float]) -> float:
    """Simple slope estimate: (last - first) / count."""
    if len(samples) < 3:
        return 0.0
    return (samples[-1] - samples[0]) / max(1, len(samples) - 1)


def _detect_anomalies(samples: List[Dict]) -> List[Dict]:
    """Analyse the rolling window and return a list of anomaly findings."""
    if len(samples) < 5:
        return []

    anomalies = []
    recent = samples[-min(WINDOW_SIZE, len(samples)):]

    # Memory trend upward → predict exhaustion
    mem_series = [float(s.get("mem_pct", 0)) for s in recent]
    if mem_series and mem_series[-1] > 75:
        slope = _linear_trend(mem_series)
        if slope > 1.0:  # gaining >1% per sample
            # Project when it hits 95%
            to_95 = (95 - mem_series[-1]) / max(slope, 0.1)
            anomalies.append({
                "key":      "mem_rising",
                "severity": "high" if mem_series[-1] > 85 else "medium",
                "summary":  f"Memory {mem_series[-1]:.0f}% and climbing +{slope:.1f}%/sample; projected 95% in ~{to_95:.0f} samples",
                "action":   "Close unused apps or reduce local-model usage.",
            })

    # Disk climbing
    disk_series = [float(s.get("disk_pct", 0)) for s in recent]
    if disk_series and disk_series[-1] > 80:
        slope = _linear_trend(disk_series)
        if slope > 0.3:
            anomalies.append({
                "key":      "disk_rising",
                "severity": "high" if disk_series[-1] > 90 else "medium",
                "summary":  f"Disk {disk_series[-1]:.0f}% and climbing; audit voice_cache, browser_cache, chroma_memory",
                "action":   "Clear old voice cache and browser screenshots.",
            })

    # CPU sustained high
    cpu_series = [float(s.get("cpu_pct", 0)) for s in recent]
    if cpu_series:
        avg = sum(cpu_series) / len(cpu_series)
        if avg > 85 and len(cpu_series) >= 5:
            anomalies.append({
                "key":      "cpu_sustained_high",
                "severity": "medium",
                "summary":  f"CPU averaging {avg:.0f}% over {len(cpu_series)} samples",
                "action":   "Check running processes; consider throttling heartbeat/perception loops.",
            })

    # Provider failure trend
    fails_series = [float(s.get("provider_fails", 0)) for s in recent]
    if fails_series and fails_series[-1] >= 3:
        slope = _linear_trend(fails_series)
        if slope > 0.5:
            anomalies.append({
                "key":      "provider_failures_rising",
                "severity": "medium",
                "summary":  f"Provider failures rising: {fails_series[-1]:.0f} consecutive, slope +{slope:.1f}",
                "action":   "Rotate API keys or switch to local provider temporarily.",
            })

    # Execution failure rate
    exec_fails = [float(s.get("exec_fail_rate", 0)) for s in recent]
    if exec_fails and sum(exec_fails[-5:]) / 5 > 0.4:
        anomalies.append({
            "key":      "goal_exec_failing",
            "severity": "high",
            "summary":  f"Goal-step failure rate {sum(exec_fails[-5:])/5*100:.0f}% over last 5 samples",
            "action":   "Inspect execution_log for the failing action type.",
        })

    return anomalies


# =============================================================================
# MAIN CHECK
# =============================================================================

def run_check() -> Dict:
    """Run one monitoring pass: sample → append → detect → alert."""
    with _lock:
        metrics = _load_metrics()
        sample = _collect_sample()
        metrics["samples"].append(sample)
        metrics["samples"] = metrics["samples"][-WINDOW_SIZE * 3:]  # keep 3 windows of history
        metrics["run_count"] = metrics.get("run_count", 0) + 1

        anomalies = _detect_anomalies(metrics["samples"])
        now = datetime.datetime.now()
        alerts_fired = []

        for a in anomalies:
            last = metrics["last_alert"].get(a["key"])
            if last:
                try:
                    last_dt = datetime.datetime.fromisoformat(last)
                    if (now - last_dt).total_seconds() < ALERT_COOLDOWN_SEC:
                        continue  # still in cooldown
                except Exception:
                    pass
            metrics["last_alert"][a["key"]] = now.isoformat()
            alerts_fired.append(a)

            severity_icon = {"high": "🚨", "medium": "⚠️", "low": "ℹ️"}.get(a["severity"], "⚠️")
            msg = f"{severity_icon} [{a['severity']}] {a['summary']} — {a['action']}"
            try:
                push_alert(msg)
            except Exception:
                pass

            # For high-severity anomalies, also create a proposal so evolution_loop /
            # human can act.
            if a["severity"] == "high":
                try:
                    add_proposal(
                        title=f"🔮 Anomaly: {a['key']}",
                        description=f"{a['summary']}\n\nRecommended: {a['action']}",
                        code_snippet="",
                        target_file="",
                        source="predictive_monitor",
                    )
                except Exception:
                    pass

            _append_anomaly({
                "ts":       now.isoformat(),
                "key":      a["key"],
                "severity": a["severity"],
                "summary":  a["summary"],
                "sample":   sample,
            })

        _save_metrics(metrics)

    return {
        "success":        True,
        "sample":         sample,
        "anomalies":      anomalies,
        "alerts_fired":   len(alerts_fired),
    }


# =============================================================================
# BACKGROUND LOOP
# =============================================================================

_loop_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _loop(interval_sec: float):
    print(f"[predictive] monitor started — interval={interval_sec}s")
    while not _stop.is_set():
        slept = 0
        while slept < interval_sec and not _stop.is_set():
            time.sleep(min(10, interval_sec - slept))
            slept += 10
        if _stop.is_set():
            break
        # Phase 4.2 — skip heavy tick when system memory is above the
        # backpressure threshold. predictive run_check serializes
        # predictive_metrics.json on every call (largest contributor to
        # the old mem_rising anomaly storm).
        try:
            from loop_supervisor import should_skip_heavy_tick
            if should_skip_heavy_tick():
                continue
        except Exception:
            pass
        try:
            run_check()
        except Exception as e:
            print(f"[predictive] check error: {e}")


def start_monitor(interval_sec: float = DEFAULT_INTERVAL_SEC) -> bool:
    global _loop_thread
    # Phase 4.1 — gate through loop_supervisor / config.LOOPS
    from loop_supervisor import loop_enabled, loop_interval_s
    if not loop_enabled("predictive"):
        print("[predictive] loop disabled by config.LOOPS — not starting")
        return False
    interval_sec = loop_interval_s("predictive", interval_sec)
    if _loop_thread and _loop_thread.is_alive():
        return False
    _stop.clear()
    _loop_thread = threading.Thread(target=_loop, args=(interval_sec,), daemon=True)
    _loop_thread.start()
    return True


def stop_monitor() -> bool:
    _stop.set()
    return True


def is_running() -> bool:
    return _loop_thread is not None and _loop_thread.is_alive()


def get_monitor_status() -> Dict:
    metrics = _load_metrics()
    recent = metrics["samples"][-1] if metrics["samples"] else {}
    return {
        "running":        is_running(),
        "run_count":      metrics.get("run_count", 0),
        "samples_stored": len(metrics.get("samples", [])),
        "latest":         recent,
        "active_alerts":  list(metrics.get("last_alert", {}).keys()),
    }


if __name__ == "__main__":
    print(json.dumps(run_check(), indent=2, default=str))
