"""
error_tracker.py — Logs every failure, scores modules.
Used by self_upgrade.py to decide what to fix next.
"""
import json
import os
import threading
import datetime
from collections import defaultdict

# Atomic write helper (retries os.replace through OneDrive locks).
try:
    from memory import atomic_json_write
except Exception:
    def atomic_json_write(filepath, data):
        with open(filepath, "w", encoding="utf-8") as _f:
            json.dump(data, _f, indent=2, ensure_ascii=False)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ERROR_LOG = os.path.join(_BASE_DIR, "error_log.json")
_lock = threading.Lock()


def log_failure(module: str, function: str, error: str,
                context: dict = None, tb: str = None):
    """Record a failure. Module = filename without .py.
    tb: full traceback string (pass traceback.format_exc() at call site)."""
    import traceback as _tb
    auto_tb = _tb.format_exc()
    entry = {
        "ts":        datetime.datetime.now().isoformat(),
        "module":    module,
        "function":  function,
        "error":     str(error)[:500],
        "context":   context or {},
        "traceback": (tb or (auto_tb if "Traceback" in auto_tb else ""))[:2000],
    }
    with _lock:
        try:
            log = []
            if os.path.exists(ERROR_LOG):
                with open(ERROR_LOG, encoding="utf-8") as f:
                    log = json.load(f)
            log.append(entry)
            log = log[-1000:]   # keep last 1000
            atomic_json_write(ERROR_LOG, log)
        except Exception:
            pass


def get_module_scores() -> dict:
    """Return {module: failure_count_last_24h}."""
    if not os.path.exists(ERROR_LOG):
        return {}
    try:
        with open(ERROR_LOG, encoding="utf-8") as f:
            log = json.load(f)
    except Exception:
        return {}
    counts = defaultdict(int)
    cutoff = (datetime.datetime.now()
              - datetime.timedelta(hours=24)).isoformat()
    for e in log:
        if e.get("ts", "") >= cutoff:
            counts[e.get("module", "?")] += 1
    return dict(counts)


def get_top_problem_module() -> str | None:
    scores = get_module_scores()
    if not scores:
        return None
    return max(scores, key=scores.get)


def recent_errors(module: str, limit: int = 20) -> list:
    """Get the most recent errors for a module."""
    if not os.path.exists(ERROR_LOG):
        return []
    try:
        with open(ERROR_LOG, encoding="utf-8") as f:
            log = json.load(f)
    except Exception:
        return []
    return [e for e in log[-200:] if e.get("module") == module][-limit:]
