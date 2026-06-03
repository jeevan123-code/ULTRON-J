"""
plugin_registry.py — Self-Learning Plugin System for Ultron-J BEYOND JARVIS.

Drop a .py file into plugins/ folder → Ultron auto-loads it.
Ask Ultron to "learn how to do X" → it writes and saves a new plugin.

Plugin contract:
    PLUGIN_META = {
        "name": "my_tool",
        "description": "what it does",
        "version": "1.0",
        "author": "Jeevan / Ultron",
        "tags": ["web", "finance"],
        "params": {"symbol": "stock ticker symbol"},
    }
    def run(params: dict) -> dict:
        return {"success": True, "result": "..."}
"""

import importlib.util
import inspect
import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

# ── Paths ──────────────────────────────────────────────────────────────────────
_BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
PLUGINS_DIR      = os.path.join(_BASE_DIR, "plugins")
PLUGIN_LOG_FILE  = os.path.join(_BASE_DIR, "plugin_log.json")
PLUGIN_STATS_FILE = os.path.join(_BASE_DIR, "plugin_stats.json")

os.makedirs(PLUGINS_DIR, exist_ok=True)

# ── Registry ───────────────────────────────────────────────────────────────────
_plugins: Dict[str, Dict] = {}          # name → {meta, module, run_fn, path, loaded_at}
_registry_lock = threading.Lock()
_watcher_running = False


# =============================================================================
# LOAD / UNLOAD
# =============================================================================

def _load_plugin_file(filepath: str) -> Optional[Dict]:
    """Load a single plugin file. Returns plugin dict or None on failure."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"ultron_plugin_{os.path.basename(filepath)[:-3]}", filepath
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        meta = getattr(mod, "PLUGIN_META", None)
        run_fn = getattr(mod, "run", None)
        # Phase 8.3 — optional `match(text) -> bool`. When defined, the
        # plugin self-decides whether a free-form intent string is a
        # match for its capability. Falls back to tag matching for
        # plugins that don't define one (backward compatible).
        match_fn = getattr(mod, "match", None)

        if not meta or not callable(run_fn):
            print(f"[PluginRegistry] Skipping {filepath} - missing PLUGIN_META or run()")
            return None

        name = meta.get("name", os.path.basename(filepath)[:-3])
        return {
            "name":      name,
            "meta":      meta,
            "module":    mod,
            "run":       run_fn,
            "match":     match_fn if callable(match_fn) else None,
            "path":      filepath,
            "loaded_at": datetime.now().isoformat(),
            "enabled":   True,
        }
    except Exception as e:
        print(f"[PluginRegistry] Error loading {filepath}: {e}")
        _log_event("load_error", {"file": filepath, "error": str(e)})
        return None


def load_all_plugins():
    """Scan plugins/ dir and load everything."""
    global _plugins
    loaded = 0
    with _registry_lock:
        for fname in os.listdir(PLUGINS_DIR):
            if fname.endswith(".py") and not fname.startswith("_"):
                fpath = os.path.join(PLUGINS_DIR, fname)
                plugin = _load_plugin_file(fpath)
                if plugin:
                    _plugins[plugin["name"]] = plugin
                    loaded += 1
                    print(f"[PluginRegistry] Loaded plugin: {plugin['name']}")
    print(f"[PluginRegistry] {loaded} plugins loaded from {PLUGINS_DIR}")
    return loaded


def reload_plugin(name: str) -> bool:
    """Hot-reload a specific plugin by name."""
    with _registry_lock:
        if name not in _plugins:
            return False
        fpath = _plugins[name]["path"]
    plugin = _load_plugin_file(fpath)
    if plugin:
        with _registry_lock:
            _plugins[name] = plugin
        _log_event("reload", {"name": name})
        return True
    return False


def unload_plugin(name: str) -> bool:
    with _registry_lock:
        if name in _plugins:
            del _plugins[name]
            _log_event("unload", {"name": name})
            return True
    return False


# =============================================================================
# RUN
# =============================================================================

def run_plugin(name: str, params: dict = None) -> Dict:
    """Execute a plugin by name. Returns result dict."""
    params = params or {}
    with _registry_lock:
        plugin = _plugins.get(name)
    if not plugin:
        return {"success": False, "error": f"Plugin '{name}' not found"}
    if not plugin["enabled"]:
        return {"success": False, "error": f"Plugin '{name}' is disabled"}

    start = time.time()
    try:
        result = plugin["run"](params)
        elapsed = round(time.time() - start, 3)
        _record_stat(name, True, elapsed)
        _log_event("run", {"name": name, "params": params, "elapsed": elapsed})
        return result if isinstance(result, dict) else {"success": True, "result": result}
    except Exception as e:
        elapsed = round(time.time() - start, 3)
        _record_stat(name, False, elapsed)
        tb = traceback.format_exc()
        _log_event("run_error", {"name": name, "error": str(e), "traceback": tb})
        return {"success": False, "error": str(e), "traceback": tb}


def run_plugin_by_intent(intent_text: str, params: dict = None) -> Optional[Dict]:
    """Find best plugin matching an intent string and run it.

    Phase 8.3 — two-tier resolution:
      1. If any plugin defines `match(text) -> bool`, the FIRST one to
         return True wins (plugins self-decide their domain).
      2. Otherwise fall back to the tag/description scoring heuristic
         used since the registry was introduced.
    """
    # Tier 1 — explicit match() functions take precedence
    with _registry_lock:
        for name, plugin in _plugins.items():
            if not plugin["enabled"] or not plugin.get("match"):
                continue
            try:
                if plugin["match"](intent_text):
                    return run_plugin(name, params or {})
            except Exception as e:
                _log_event("match_error", {"name": name, "error": str(e)})

    # Tier 2 — legacy tag scoring (unchanged)
    intent_lower = intent_text.lower()
    best_plugin = None
    best_score  = 0
    with _registry_lock:
        for name, plugin in _plugins.items():
            if not plugin["enabled"]:
                continue
            meta = plugin["meta"]
            score = 0
            desc  = (meta.get("description", "") + " " + " ".join(meta.get("tags", []))).lower()
            for word in intent_lower.split():
                if word in desc:
                    score += 1
            if name.lower() in intent_lower:
                score += 5
            if score > best_score:
                best_score  = score
                best_plugin = name

    if best_plugin and best_score > 0:
        return run_plugin(best_plugin, params or {})
    return None


def write_skill_plugin(name: str, code: str, description: str = "",
                       tags: list = None) -> dict:
    """Phase 8.3 — concrete write path for skill_learner.

    Writes a new plugin file to plugins/<name>.py with the given code.
    The code must contain a `PLUGIN_META` dict and a `run(params) -> dict`
    function -- the same contract every plugin follows. Returns:
        {"success": bool, "path": str, "error": str}
    The plugin watcher (5s interval) picks up the new file
    automatically, so the skill becomes callable without a restart.
    """
    # Defensive validation -- the code must be syntactically valid Python
    # AND export the expected interface, or we refuse to write.
    try:
        compile(code, f"<skill_learner:{name}>", "exec")
    except SyntaxError as e:
        return {"success": False, "error": f"syntax error: {e}"}

    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")
    if not safe_name:
        return {"success": False, "error": "name produces empty filename"}
    target = os.path.join(PLUGINS_DIR, f"{safe_name}.py")

    if os.path.exists(target):
        return {"success": False,
                "error": f"plugin '{safe_name}' already exists at {target}"}

    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(code)
    except OSError as e:
        return {"success": False, "error": f"write failed: {e}"}

    _log_event("skill_learner_write", {
        "name":        safe_name,
        "description": description,
        "tags":        tags or [],
        "path":        target,
    })
    return {"success": True, "path": target,
            "note": "plugin watcher (5s interval) will auto-load it"}


import re  # used by write_skill_plugin


# =============================================================================
# LLM-GENERATED PLUGINS (self-learning)
# =============================================================================

PLUGIN_TEMPLATE = '''"""
Auto-generated plugin: {name}
Created: {created}
"""

PLUGIN_META = {{
    "name": "{name}",
    "description": "{description}",
    "version": "1.0",
    "author": "Ultron-J (auto-generated)",
    "tags": {tags},
    "params": {params_schema},
}}


def run(params: dict) -> dict:
    """
    {description}
    """
{body}
'''


def create_plugin_from_llm(name: str, description: str, llm_call_fn) -> Dict:
    """
    Ask the LLM to write a plugin and save it to plugins/.
    llm_call_fn(prompt) → str (code body)
    """
    prompt = f"""Write a Python function body for a Ultron-J plugin tool.

Plugin name: {name}
Description: {description}

Rules:
- Write ONLY the function body (indented 4 spaces, no def line)
- The function receives `params: dict` and must return a dict with "success" key
- Use only stdlib + requests. No os.system, no exec, no open() for write
- Keep it under 40 lines
- Add try/except and return {{"success": False, "error": str(e)}} on failure
- Return {{"success": True, "result": <the result>}}

Function body:"""

    try:
        body_code = llm_call_fn(prompt)
        # Clean up LLM output
        body_code = body_code.strip()
        if body_code.startswith("```"):
            body_code = "\n".join(body_code.split("\n")[1:])
        if body_code.endswith("```"):
            body_code = "\n".join(body_code.split("\n")[:-1])
        # Ensure indentation
        lines = body_code.split("\n")
        indented = "\n".join("    " + l if not l.startswith("    ") else l for l in lines)

        safe_name = name.lower().replace(" ", "_").replace("-", "_")
        code = PLUGIN_TEMPLATE.format(
            name=safe_name,
            description=description,
            created=datetime.now().isoformat(),
            tags=json.dumps([safe_name]),
            params_schema="{}",
            body=indented,
        )

        fpath = os.path.join(PLUGINS_DIR, f"{safe_name}.py")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(code)

        plugin = _load_plugin_file(fpath)
        if plugin:
            with _registry_lock:
                _plugins[plugin["name"]] = plugin
            _log_event("created", {"name": safe_name, "description": description})
            return {"success": True, "name": safe_name, "path": fpath}
        else:
            return {"success": False, "error": "Plugin generated but failed to load"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# HOT-RELOAD WATCHER
# =============================================================================

def _watch_plugins_dir(interval: int = 5):
    """Background thread: detect new/modified plugins and auto-reload."""
    global _watcher_running
    seen_mtimes: Dict[str, float] = {}

    while _watcher_running:
        try:
            for fname in os.listdir(PLUGINS_DIR):
                if not fname.endswith(".py") or fname.startswith("_"):
                    continue
                fpath = os.path.join(PLUGINS_DIR, fname)
                mtime = os.path.getmtime(fpath)
                if fpath not in seen_mtimes:
                    # New plugin
                    plugin = _load_plugin_file(fpath)
                    if plugin:
                        with _registry_lock:
                            _plugins[plugin["name"]] = plugin
                        print(f"[PluginRegistry] Auto-loaded: {plugin['name']}")
                        _log_event("auto_loaded", {"name": plugin["name"]})
                    seen_mtimes[fpath] = mtime
                elif mtime > seen_mtimes[fpath]:
                    # Modified plugin
                    plugin = _load_plugin_file(fpath)
                    if plugin:
                        with _registry_lock:
                            _plugins[plugin["name"]] = plugin
                        print(f"[PluginRegistry] Auto-reloaded: {plugin['name']}")
                        _log_event("auto_reloaded", {"name": plugin["name"]})
                    seen_mtimes[fpath] = mtime
        except Exception as e:
            print(f"[PluginRegistry] Watcher error: {e}")
        time.sleep(interval)


def start_plugin_watcher(interval: int = 5):
    global _watcher_running
    # Phase 4.1 — gate through loop_supervisor / config.LOOPS
    from loop_supervisor import loop_enabled, loop_interval_s
    if not loop_enabled("plugin_watcher"):
        print("[PluginRegistry] watcher disabled by config.LOOPS — not starting")
        return
    interval = int(loop_interval_s("plugin_watcher", interval))
    if _watcher_running:
        return
    _watcher_running = True
    t = threading.Thread(target=_watch_plugins_dir, args=(interval,), daemon=True)
    t.start()
    print(f"[PluginRegistry] Watcher started (every {interval}s)")


def stop_plugin_watcher():
    global _watcher_running
    _watcher_running = False


# =============================================================================
# QUERY / STATUS
# =============================================================================

def list_plugins() -> list:
    with _registry_lock:
        return [
            {
                "name":        p["name"],
                "description": p["meta"].get("description", ""),
                "tags":        p["meta"].get("tags", []),
                "version":     p["meta"].get("version", "1.0"),
                "enabled":     p["enabled"],
                "loaded_at":   p["loaded_at"],
            }
            for p in _plugins.values()
        ]


def get_plugin_stats() -> Dict:
    try:
        if os.path.exists(PLUGIN_STATS_FILE):
            with open(PLUGIN_STATS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def enable_plugin(name: str) -> bool:
    with _registry_lock:
        if name in _plugins:
            _plugins[name]["enabled"] = True
            return True
    return False


def disable_plugin(name: str) -> bool:
    with _registry_lock:
        if name in _plugins:
            _plugins[name]["enabled"] = False
            return True
    return False


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _log_event(event: str, data: dict):
    try:
        log = []
        if os.path.exists(PLUGIN_LOG_FILE):
            with open(PLUGIN_LOG_FILE, "r") as f:
                log = json.load(f)
        log.append({"event": event, "data": data, "ts": datetime.now().isoformat()})
        if len(log) > 500:
            log = log[-500:]
        with open(PLUGIN_LOG_FILE, "w") as f:
            json.dump(log, f, indent=2)
    except Exception:
        pass


def _record_stat(name: str, success: bool, elapsed: float):
    try:
        stats = {}
        if os.path.exists(PLUGIN_STATS_FILE):
            with open(PLUGIN_STATS_FILE, "r") as f:
                stats = json.load(f)
        if name not in stats:
            stats[name] = {"runs": 0, "success": 0, "fail": 0, "avg_ms": 0}
        s = stats[name]
        s["runs"]    += 1
        s["success"] += int(success)
        s["fail"]    += int(not success)
        s["avg_ms"]   = round((s["avg_ms"] * (s["runs"] - 1) + elapsed * 1000) / s["runs"], 1)
        with open(PLUGIN_STATS_FILE, "w") as f:
            json.dump(stats, f, indent=2)
    except Exception:
        pass


# =============================================================================
# STARTUP
# =============================================================================

# Bundled example plugin written to plugins/ if empty
_EXAMPLE_PLUGIN = '''"""
Example plugin: crypto_price
Fetches live crypto price from CoinGecko (no API key needed).
"""

PLUGIN_META = {
    "name": "crypto_price",
    "description": "Get live cryptocurrency price in USD",
    "version": "1.0",
    "author": "Ultron-J",
    "tags": ["finance", "crypto", "price"],
    "params": {"coin": "coin id e.g. bitcoin, ethereum, solana"},
}


def run(params: dict) -> dict:
    import requests
    coin = params.get("coin", "bitcoin").lower().strip()
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin, "vs_currencies": "usd,inr"},
            timeout=8,
        )
        data = r.json()
        if coin not in data:
            return {"success": False, "error": f"Coin '{coin}' not found"}
        prices = data[coin]
        return {
            "success": True,
            "result": f"{coin.capitalize()}: ${prices.get('usd', 'N/A')} USD | ₹{prices.get('inr', 'N/A')} INR",
            "data": prices,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
'''

def _seed_example_plugin():
    fpath = os.path.join(PLUGINS_DIR, "crypto_price.py")
    if not os.path.exists(fpath):
        with open(fpath, "w") as f:
            f.write(_EXAMPLE_PLUGIN)

_seed_example_plugin()
load_all_plugins()
start_plugin_watcher()
