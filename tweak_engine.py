"""
tweak_engine.py — Safely edit config.py without crashing Ultron-J.

The roadmap calls for Ultron to be able to edit its own config and plugin
registry. self_modify.py handles arbitrary patches, but a config change is
a special case that wants tighter guarantees:

  1. PARSE-SAFE         The file must still import after the edit.
  2. TYPE-SAFE          If the original value was an int, the new one must parse as int.
  3. BOUNDED            Known settings have known safe ranges — outside ⇒ reject.
  4. BACKED-UP          A timestamped backup is taken before every edit.
  5. AUDIT-LOGGED       Every tweak (success or reject) is logged.
  6. ROLLBACKABLE       rollback() restores the most recent backup.

This module is used by:
  - evolution_loop  proposals with kind="config_tweak" can be applied here.
  - human_interface operator approval flow for Ultron-generated tweaks.
  - voice commands  "Ultron, bump retry attempts to 8" → tweak MAX_RETRY_ATTEMPTS

Public API:
    list_tweakable()                     → dict of var → {current, type, bounds}
    tweak(name, new_value)               → {success, old, new, error}
    rollback()                           → {success, restored_from}
    list_backups()                       → list of backup files
    get_tweak_log(n=30)                  → audit log
"""

import ast
import json
import os
import re
import shutil
import importlib
import datetime
import threading
from typing import Dict, List, Optional, Any, Tuple

try:
    from config import _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))


CONFIG_FILE      = os.path.join(_BASE_DIR, "config.py")
BACKUP_DIR       = os.path.join(_BASE_DIR, "config_backups")
TWEAK_LOG_FILE   = os.path.join(_BASE_DIR, "tweak_log.json")

os.makedirs(BACKUP_DIR, exist_ok=True)

# =============================================================================
# ALLOWED TWEAKS
# =============================================================================
# Only these variables are editable by tweak(). Everything else is rejected.
# Add entries carefully — changing the wrong thing can crash Ultron.
#
# Schema:
#   name: {
#     "type":      "int" | "float" | "bool" | "str",
#     "min":       optional numeric lower bound (inclusive)
#     "max":       optional numeric upper bound (inclusive)
#     "choices":   optional list of valid string values
#     "restart":   True if Ultron-J must be restarted for the change to take effect
#     "reason":    human-readable note
#   }

ALLOWED_TWEAKS: Dict[str, Dict] = {
    # ── Hard caps (safe to raise within bounds) ──
    "MAX_CONVERSATIONS":     {"type": "int",   "min": 50,   "max": 5000,  "restart": False,
                              "reason": "conversations kept in memory.json before trimming"},
    "MAX_FACTS":             {"type": "int",   "min": 50,   "max": 5000,  "restart": False,
                              "reason": "facts about Jeevan kept in memory"},
    "MAX_HISTORY_ITEMS":     {"type": "int",   "min": 5,    "max": 100,   "restart": False,
                              "reason": "conversation turns passed to LLM"},
    "MAX_INPUT_CHARS":       {"type": "int",   "min": 500,  "max": 16000, "restart": False,
                              "reason": "max user message length"},
    "MAX_CONTEXT_CHARS":     {"type": "int",   "min": 500,  "max": 16000, "restart": False,
                              "reason": "max context injected into prompts"},
    "SEMANTIC_TOP_K":        {"type": "int",   "min": 3,    "max": 30,    "restart": False,
                              "reason": "top-k for vector recall"},
    "MAX_RETRY_ATTEMPTS":    {"type": "int",   "min": 1,    "max": 10,    "restart": False,
                              "reason": "search/query reframings attempted"},

    # ── Timing ──
    "MONITOR_INTERVAL":      {"type": "int",   "min": 15,   "max": 3600,  "restart": True,
                              "reason": "system monitor tick (seconds)"},
    "HEARTBEAT_INTERVAL":    {"type": "int",   "min": 60,   "max": 3600,  "restart": True,
                              "reason": "autonomous heartbeat (seconds)"},
    "PERCEPTION_INTERVAL":   {"type": "int",   "min": 5,    "max": 600,   "restart": True,
                              "reason": "perception loop (seconds)"},
    "CLIPBOARD_INTERVAL":    {"type": "int",   "min": 2,    "max": 60,    "restart": True,
                              "reason": "clipboard poll (seconds)"},

    # ── Voice ──
    "VOICE_MAX_TTS_CHARS":       {"type": "int",  "min": 50,  "max": 2000, "restart": False,
                                  "reason": "max chars sent to TTS at once"},
    "VOICE_RESPONSE_MAX_WORDS":  {"type": "int",  "min": 20,  "max": 300,  "restart": False,
                                  "reason": "max words in a voice reply"},
    "VOICE_ENABLED":             {"type": "bool", "restart": True,
                                  "reason": "global voice engine on/off"},

    # ── Identity ──
    "JEEVAN_NAME":               {"type": "str",  "restart": True,
                                  "reason": "Jeevan's display name"},
    "JEEVAN_LOCATION":           {"type": "str",  "restart": True,
                                  "reason": "Jeevan's location"},
    "JEEVAN_TIMEZONE":           {"type": "str",  "restart": True,
                                  "reason": "IANA timezone"},
    "AGENT_NAME":                {"type": "str",  "restart": True,
                                  "reason": "Ultron-J's display name"},
    "WAKE_WORD":                 {"type": "str",  "restart": True,
                                  "reason": "wake word for voice listener"},
    "SELF_AWARE_KEYWORD":        {"type": "str",  "restart": False,
                                  "reason": "keyword that triggers self-awareness block"},

    # ── Mood schedule ──
    "MORNING_MOOD":              {"type": "str", "restart": False,
                                  "choices": ["FOCUSED","CURIOUS","ALERT","CONCERNED",
                                              "DETERMINED","ANALYTICAL","IDLE"]},
    "AFTERNOON_MOOD":            {"type": "str", "restart": False,
                                  "choices": ["FOCUSED","CURIOUS","ALERT","CONCERNED",
                                              "DETERMINED","ANALYTICAL","IDLE"]},
    "EVENING_MOOD":              {"type": "str", "restart": False,
                                  "choices": ["FOCUSED","CURIOUS","ALERT","CONCERNED",
                                              "DETERMINED","ANALYTICAL","IDLE"]},
    "NIGHT_MOOD":                {"type": "str", "restart": False,
                                  "choices": ["FOCUSED","CURIOUS","ALERT","CONCERNED",
                                              "DETERMINED","ANALYTICAL","IDLE"]},

    # ── Sandbox ──
    "CODE_SANDBOX_TIMEOUT":      {"type": "int",  "min": 2,   "max": 60,    "restart": False,
                                  "reason": "sandbox execution timeout"},
    "CODE_SANDBOX_MAX_OUTPUT":   {"type": "int",  "min": 500, "max": 50000, "restart": False,
                                  "reason": "max bytes returned from sandbox"},

    # ── Reflection ──
    "REFLECT_AFTER_N_GOALS":     {"type": "int",  "min": 1,   "max": 100, "restart": False},
    "REFLECT_INTERVAL_HOURS":    {"type": "int",  "min": 1,   "max": 72,  "restart": True},

    # ── Provider health ──
    "PROVIDER_FAILURE_THRESHOLD":{"type": "int",  "min": 1,   "max": 10,  "restart": False},
    "PROVIDER_HEALTH_TTL":       {"type": "int",  "min": 60,  "max": 3600, "restart": False},
}


_lock = threading.Lock()


# =============================================================================
# AUDIT LOG
# =============================================================================

def _append_log(entry: Dict):
    entries = _load_log()
    entries.append(entry)
    try:
        with open(TWEAK_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(entries[-200:], f, indent=2)
    except Exception as e:
        print(f"[tweak_engine] log write failed: {e}")


def _load_log() -> List[Dict]:
    if not os.path.exists(TWEAK_LOG_FILE):
        return []
    try:
        with open(TWEAK_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def get_tweak_log(n: int = 30) -> List[Dict]:
    return _load_log()[-n:][::-1]


# =============================================================================
# INTROSPECTION
# =============================================================================

def list_tweakable() -> Dict[str, Dict]:
    """Return the set of tweakable variables with their current values."""
    out = {}
    try:
        import config
        importlib.reload(config)
    except Exception as e:
        return {"error": str(e)}

    for name, spec in ALLOWED_TWEAKS.items():
        current = getattr(config, name, None)
        out[name] = {
            "current":  current,
            "type":     spec.get("type"),
            "min":      spec.get("min"),
            "max":      spec.get("max"),
            "choices":  spec.get("choices"),
            "restart":  spec.get("restart", False),
            "reason":   spec.get("reason", ""),
        }
    return out


# =============================================================================
# VALIDATION
# =============================================================================

def _validate_value(name: str, raw_value) -> Tuple[bool, Any, str]:
    """Convert and validate a new value. Returns (ok, coerced_value, error_msg)."""
    if name not in ALLOWED_TWEAKS:
        return False, None, f"{name} is not a tweakable variable"

    spec = ALLOWED_TWEAKS[name]
    expected_type = spec["type"]

    # Coerce
    try:
        if expected_type == "int":
            coerced = int(raw_value)
        elif expected_type == "float":
            coerced = float(raw_value)
        elif expected_type == "bool":
            if isinstance(raw_value, bool):
                coerced = raw_value
            elif isinstance(raw_value, str):
                rl = raw_value.strip().lower()
                if rl in ("true", "yes", "1", "on"):
                    coerced = True
                elif rl in ("false", "no", "0", "off"):
                    coerced = False
                else:
                    return False, None, f"cannot parse {raw_value!r} as bool"
            else:
                coerced = bool(raw_value)
        elif expected_type == "str":
            coerced = str(raw_value).strip()
            if not coerced:
                return False, None, "string value cannot be empty"
        else:
            return False, None, f"unknown type in spec: {expected_type}"
    except Exception as e:
        return False, None, f"value coercion failed: {e}"

    # Bounds
    if "min" in spec and spec["min"] is not None and isinstance(coerced, (int, float)):
        if coerced < spec["min"]:
            return False, None, f"value {coerced} below minimum {spec['min']}"
    if "max" in spec and spec["max"] is not None and isinstance(coerced, (int, float)):
        if coerced > spec["max"]:
            return False, None, f"value {coerced} above maximum {spec['max']}"

    # Choices
    if "choices" in spec and spec["choices"] is not None:
        if coerced not in spec["choices"]:
            return False, None, f"value must be one of {spec['choices']}"

    return True, coerced, ""


# =============================================================================
# BACKUP
# =============================================================================

def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _backup_config() -> Optional[str]:
    try:
        target = os.path.join(BACKUP_DIR, f"config.py.{_timestamp()}.bak")
        shutil.copy2(CONFIG_FILE, target)
        # Keep only last 30 backups
        backups = sorted(os.listdir(BACKUP_DIR))
        while len(backups) > 30:
            try:
                os.remove(os.path.join(BACKUP_DIR, backups.pop(0)))
            except Exception:
                break
        return target
    except Exception as e:
        print(f"[tweak_engine] backup failed: {e}")
        return None


def list_backups() -> List[str]:
    if not os.path.exists(BACKUP_DIR):
        return []
    return sorted(os.listdir(BACKUP_DIR), reverse=True)


# =============================================================================
# EDIT
# =============================================================================

_ASSIGN_RE_CACHE: Dict[str, re.Pattern] = {}


def _edit_pattern(name: str) -> re.Pattern:
    if name not in _ASSIGN_RE_CACHE:
        # Matches "NAME  =  <value>  # optional comment"  at line start.
        # We preserve the comment if present.
        _ASSIGN_RE_CACHE[name] = re.compile(
            r"^(" + re.escape(name) + r"\s*=\s*)([^\n#]+?)(\s*(?:#.*)?)$",
            re.MULTILINE,
        )
    return _ASSIGN_RE_CACHE[name]


def _format_value(v: Any, kind: str) -> str:
    if kind == "str":
        # Use repr to get correct quoting and escaping
        return repr(v)
    if kind == "bool":
        return "True" if v else "False"
    return str(v)


def tweak(name: str, new_value) -> Dict:
    """Apply a single config tweak.

    Returns:
        {"success": bool, "old": ..., "new": ..., "error": str, "backup": path, "restart_required": bool}
    """
    with _lock:
        ok, coerced, err = _validate_value(name, new_value)
        if not ok:
            entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "action":    "reject",
                "name":      name,
                "value":     str(new_value),
                "error":     err,
            }
            _append_log(entry)
            return {"success": False, "error": err, "name": name, "new": new_value}

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                original = f.read()
        except Exception as e:
            return {"success": False, "error": f"cannot read config: {e}"}

        pattern = _edit_pattern(name)
        match = pattern.search(original)
        if not match:
            return {"success": False, "error": f"{name} assignment not found in config.py"}

        old_src_value = match.group(2).strip()
        new_src_value = _format_value(coerced, ALLOWED_TWEAKS[name]["type"])

        # Build new file content
        new_content = pattern.sub(
            lambda m: f"{m.group(1)}{new_src_value}{m.group(3)}",
            original,
            count=1,
        )

        if new_content == original:
            return {"success": False, "error": "edit produced no change — possibly already at this value"}

        # Parse-check: make sure the file is still valid Python
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            return {"success": False, "error": f"edit would break parse: {e}"}

        # Backup original
        backup_path = _backup_config()
        if not backup_path:
            return {"success": False, "error": "backup failed — aborting"}

        # Write new content
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(new_content)
        except Exception as e:
            return {"success": False, "error": f"write failed: {e}"}

        # Hot-reload if not restart-required
        restart_required = ALLOWED_TWEAKS[name].get("restart", False)
        if not restart_required:
            try:
                import config
                importlib.reload(config)
            except Exception as e:
                # The new content parsed but reload failed — roll back
                print(f"[tweak_engine] reload failed: {e} — rolling back")
                try:
                    shutil.copy2(backup_path, CONFIG_FILE)
                except Exception:
                    pass
                return {"success": False, "error": f"reload failed, rolled back: {e}"}

        entry = {
            "timestamp":        datetime.datetime.now().isoformat(),
            "action":           "apply",
            "name":             name,
            "old":              old_src_value,
            "new":              new_src_value,
            "backup":           backup_path,
            "restart_required": restart_required,
        }
        _append_log(entry)

        return {
            "success":          True,
            "name":             name,
            "old":              old_src_value,
            "new":              new_src_value,
            "backup":           backup_path,
            "restart_required": restart_required,
        }


def rollback() -> Dict:
    """Restore the most recent backup."""
    with _lock:
        backups = list_backups()
        if not backups:
            return {"success": False, "error": "no backups to restore"}
        latest = os.path.join(BACKUP_DIR, backups[0])
        try:
            shutil.copy2(latest, CONFIG_FILE)
        except Exception as e:
            return {"success": False, "error": f"restore failed: {e}"}
        try:
            import config
            importlib.reload(config)
        except Exception as e:
            return {"success": False, "error": f"restored but reload failed: {e}", "restored_from": latest}
        entry = {
            "timestamp":     datetime.datetime.now().isoformat(),
            "action":        "rollback",
            "restored_from": latest,
        }
        _append_log(entry)
        return {"success": True, "restored_from": latest}


# =============================================================================
# SMOKE TEST
# =============================================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        r = tweak(sys.argv[1], sys.argv[2])
        print(json.dumps(r, indent=2))
    else:
        tweakable = list_tweakable()
        print(f"Tweakable variables: {len(tweakable)}")
        for name, meta in list(tweakable.items())[:10]:
            print(f"  {name}: current={meta.get('current')} type={meta.get('type')}")
