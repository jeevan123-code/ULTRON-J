"""
system_monitor.py — System awareness, alerts, proposals, and the autonomous heartbeat.
ULTIMATE version.

ULTIMATE UPGRADES:
- Network connectivity status (knows when offline)
- Battery/laptop detection and monitoring
- CPU temperature monitoring (if available)
- Enhanced self-awareness block with personality mood
- More sophisticated stale project detection with scoring
- Better briefing generation with weather, goals, and pattern context
- Hardware health scoring: 0-100 overall system health
- Process intelligence: knows which processes are Jeevan's dev tools
"""

import datetime
import json
import os
import platform
import subprocess
import sys
import threading
import time

from config import (
    _BASE_DIR, PROPOSALS_FILE, SYSTEM_SNAPSHOT,
    MONITOR_INTERVAL, SELF_AWARE_CACHE_TTL, HEARTBEAT_INTERVAL,
    JEEVAN_NAME, JEEVAN_LOCATION, SELF_AWARE_KEYWORD,
    HEARTBEAT_FILE, AGENT_VERSION,
)
from memory import atomic_json_write

# ── Optional psutil ────────────────────────────────────────────────────────────
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ── Heartbeat suggestion queue ────────────────────────────────────────────────
_heartbeat_suggestions = []
_heartbeat_lock        = threading.Lock()
_last_briefing_hour    = -1

# =============================================================================
# ALERTS — thread-safe ring buffer
# =============================================================================

_alerts      = []
_alerts_lock = threading.Lock()


def push_alert(msg: str):
    with _alerts_lock:
        _alerts.append({"time": datetime.datetime.now().strftime("%H:%M:%S"), "msg": msg})
        if len(_alerts) > 50:
            _alerts.pop(0)


def pop_alerts() -> list:
    with _alerts_lock:
        out = list(_alerts)
        _alerts.clear()
    return out

# =============================================================================
# HARDWARE / SYSTEM QUERIES
# =============================================================================

def get_installed_packages() -> list:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=15,
        )
        return json.loads(result.stdout)
    except Exception:
        return []


def get_running_processes() -> list:
    if not PSUTIL_AVAILABLE:
        return []
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
        return procs[:20]
    except Exception:
        return []


def get_disk_usage() -> dict:
    if not PSUTIL_AVAILABLE:
        return {}
    try:
        usage = {}
        for part in psutil.disk_partitions():
            try:
                u = psutil.disk_usage(part.mountpoint)
                usage[part.mountpoint] = {
                    "total_gb": round(u.total / 1e9, 1),
                    "used_gb":  round(u.used  / 1e9, 1),
                    "free_gb":  round(u.free  / 1e9, 1),
                    "percent":  u.percent,
                }
            except Exception:
                pass
        return usage
    except Exception:
        return {}


def get_memory_usage() -> dict:
    if not PSUTIL_AVAILABLE:
        return {}
    try:
        vm = psutil.virtual_memory()
        return {
            "total_gb": round(vm.total    / 1e9, 1),
            "used_gb":  round(vm.used     / 1e9, 1),
            "free_gb":  round(vm.available / 1e9, 1),
            "percent":  vm.percent,
        }
    except Exception:
        return {}


def get_cpu_usage() -> dict:
    """Get CPU usage and temperature if available."""
    if not PSUTIL_AVAILABLE:
        return {}
    try:
        cpu_pct   = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        result    = {"percent": cpu_pct, "cores": cpu_count}

        # Temperature (Linux/Mac only)
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        result["temp_c"] = round(entries[0].current, 1)
                        result["temp_source"] = name
                        break
        except Exception:
            pass

        return result
    except Exception:
        return {}


def get_battery_status() -> dict:
    """Get battery status if this is a laptop."""
    if not PSUTIL_AVAILABLE:
        return {}
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return {}
        return {
            "percent":    round(battery.percent, 1),
            "plugged":    battery.power_plugged,
            "time_left":  battery.secsleft if battery.secsleft > 0 else None,
            "critical":   battery.percent < 15 and not battery.power_plugged,
            "low":        battery.percent < 30 and not battery.power_plugged,
        }
    except Exception:
        return {}


def get_desktop_files() -> list:
    try:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(desktop):
            desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
        if not os.path.exists(desktop):
            return []
        items = []
        for name in os.listdir(desktop):
            full = os.path.join(desktop, name)
            items.append({
                "name":    name,
                "type":    "folder" if os.path.isdir(full) else "file",
                "size_kb": round(os.path.getsize(full) / 1024, 1) if os.path.isfile(full) else 0,
            })
        return sorted(items, key=lambda x: x["name"].lower())
    except Exception:
        return []


def get_ollama_models() -> list:
    try:
        import requests as _req
        res = _req.get("http://localhost:11434/api/tags", timeout=5)
        if res.status_code == 200:
            return [m["name"] for m in res.json().get("models", [])]
    except Exception:
        pass
    return []


def get_system_health_score() -> int:
    """
    Calculate an overall system health score 0-100.
    100 = perfect, 0 = critical.
    """
    score = 100

    mem = get_memory_usage()
    if mem:
        score -= max(0, (mem.get("percent", 0) - 50) // 5)  # lose points over 50%

    disk = get_disk_usage()
    # Phase 4 fix — exclude pseudo-filesystems and snap mounts. squashfs
    # snap mounts are 100% used BY DESIGN (read-only loop devices) and
    # were dragging health_score by -25 each. On this Linux box there
    # are 4+ snap mounts, which alone pinned health_score around 17.
    _PSEUDO_PREFIXES = ("/snap/", "/var/lib/docker/", "/proc/", "/sys/", "/dev/")
    for mount, d in disk.items():
        if any(mount.startswith(p) for p in _PSEUDO_PREFIXES):
            continue
        if d.get("percent", 0) > 80:
            score -= 10
        if d.get("percent", 0) > 90:
            score -= 15

    cpu = get_cpu_usage()
    if cpu.get("percent", 0) > 80:
        score -= 10

    battery = get_battery_status()
    if battery.get("critical"):
        score -= 20
    elif battery.get("low"):
        score -= 5

    temp = cpu.get("temp_c", 0)
    if temp > 80:
        score -= 15
    elif temp > 70:
        score -= 5

    return max(0, min(100, score))


def get_dev_processes() -> list:
    """Get processes that look like Jeevan's development tools."""
    processes = get_running_processes()
    dev_names = {
        "python", "python3", "node", "npm", "code",
        "pycharm", "ollama", "flask", "uvicorn", "chrome",
        "firefox", "jupyter", "postgres", "mysql", "redis",
        "git", "docker",
    }
    return [
        p for p in processes
        if any(dev in (p.get("name", "") or "").lower() for dev in dev_names)
    ]

# =============================================================================
# SELF-AWARENESS BLOCK — KARTHA keyword only
# =============================================================================

_self_aware_cache     = None
_self_aware_cache_at  = None
_self_aware_cache_lock = threading.Lock()


def build_self_awareness_block() -> str:
    """
    Build Ultron's full self-awareness block.
    ONLY called when KARTHA keyword is used — massive token savings on normal queries.
    Cached for SELF_AWARE_CACHE_TTL seconds.
    """
    global _self_aware_cache, _self_aware_cache_at

    with _self_aware_cache_lock:
        now = datetime.datetime.now()
        if (
            _self_aware_cache is not None
            and _self_aware_cache_at is not None
            and (now - _self_aware_cache_at).total_seconds() < SELF_AWARE_CACHE_TTL
        ):
            return _self_aware_cache

    lines = [
        f"=== ULTRON-J SELF-AWARENESS BLOCK v{AGENT_VERSION} ===",
        f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Platform: {platform.system()} {platform.release()}",
        f"Python: {sys.version[:20]}",
        "",
    ]

    # Hardware
    mem  = get_memory_usage()
    disk = get_disk_usage()
    cpu  = get_cpu_usage()
    bat  = get_battery_status()

    if mem:
        lines.append(f"RAM: {mem.get('used_gb', '?')}GB / {mem.get('total_gb', '?')}GB ({mem.get('percent', '?')}%)")
    if cpu:
        temp_str = f" | {cpu['temp_c']}°C" if cpu.get("temp_c") else ""
        lines.append(f"CPU: {cpu.get('percent', '?')}% ({cpu.get('cores', '?')} cores){temp_str}")
    if bat:
        plug_str = "🔌 charging" if bat.get("plugged") else "🔋 battery"
        lines.append(f"Battery: {bat.get('percent', '?')}% ({plug_str})")

    for mount, d in disk.items():
        lines.append(f"Disk [{mount}]: {d.get('free_gb', '?')}GB free / {d.get('total_gb', '?')}GB")

    lines.append(f"Health Score: {get_system_health_score()}/100")
    lines.append("")

    # Source files
    code_files = read_own_code()
    if code_files:
        lines.append("Source files:")
        for fname, info in code_files.items():
            lines.append(f"  {fname}: {info.get('lines', '?')} lines")
    lines.append("")

    # Personality
    try:
        from personality import get_personality_status
        ps = get_personality_status()
        lines.append(f"Mood: {ps['mood']} {ps['mood_icon']} | Energy: {int(ps['energy_level']*100)}%")
        lines.append(f"Tasks today: {ps['task_count_today']}")
    except Exception:
        pass

    # Agent state
    try:
        from decision_engine import load_agent_state, load_goals, GoalStatus
        state = load_agent_state()
        goals = load_goals()
        pending   = len([g for g in goals if g["status"] == GoalStatus.PENDING])
        active    = len([g for g in goals if g["status"] in (GoalStatus.ACTIVE, GoalStatus.EXECUTING)])
        completed = len([g for g in goals if g["status"] == GoalStatus.COMPLETED])
        lines.append(f"Goals: {pending} pending, {active} active, {completed} completed")
    except Exception:
        pass

    # Ollama models
    models = get_ollama_models()
    if models:
        lines.append(f"Ollama models: {', '.join(models)}")

    lines.append(f"=== END SELF-AWARENESS BLOCK ===")

    result = "\n".join(lines)

    with _self_aware_cache_lock:
        _self_aware_cache    = result
        _self_aware_cache_at = datetime.datetime.now()

    return result


def read_own_code() -> dict:
    """Read Ultron-J's own source files. Only called on KARTHA."""
    code_files = {}
    extensions = {".py"}
    skip_dirs  = {"__pycache__", "chroma_memory", ".git", "node_modules", "venv", ".venv"}
    try:
        for root, dirs, files in os.walk(_BASE_DIR):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                ext = os.path.splitext(fname)[1]
                if ext in extensions:
                    full = os.path.join(root, fname)
                    try:
                        with open(full, "r", encoding="utf-8") as f:
                            content = f.read()
                        code_files[fname] = {
                            "lines": len(content.splitlines()),
                            "size":  len(content),
                        }
                    except Exception:
                        pass
    except Exception:
        pass
    return code_files

# =============================================================================
# HEARTBEAT SUGGESTIONS
# =============================================================================

def _push_heartbeat_suggestion(msg: str):
    with _heartbeat_lock:
        _heartbeat_suggestions.append({
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "msg":  msg,
        })
        if len(_heartbeat_suggestions) > 30:
            _heartbeat_suggestions.pop(0)


def get_heartbeat_suggestions() -> list:
    with _heartbeat_lock:
        out = list(_heartbeat_suggestions)
        _heartbeat_suggestions.clear()
    return out

# =============================================================================
# DETECT NEW FILES FOR SUGGESTION
# =============================================================================

def detect_new_files_for_suggestion(old_set: set, new_set: set) -> list:
    added = new_set - old_set
    suggestions = []
    for fname in added:
        ext = os.path.splitext(fname)[1].lower()
        if ext in {".py", ".js", ".ts", ".ipynb"}:
            suggestions.append(f"👁️ New code file: '{fname}'. Want me to review it?")
        elif ext in {".pdf", ".docx"}:
            suggestions.append(f"📄 New document: '{fname}'. Want a summary?")
        elif fname.lower() in {"requirements.txt", "package.json", "dockerfile"}:
            suggestions.append(f"🚀 New project marker: '{fname}'. New project detected?")
    return suggestions

# =============================================================================
# PROPOSALS
# =============================================================================

def load_proposals() -> list:
    if os.path.exists(PROPOSALS_FILE):
        try:
            with open(PROPOSALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_proposals(proposals: list):
    atomic_json_write(PROPOSALS_FILE, proposals)


def add_proposal(title, description, code_snippet="", target_file=""):
    proposals = load_proposals()
    # Deduplicate by title
    if any(p.get("title") == title for p in proposals):
        return
    proposals.append({
        "id":          len(proposals),
        "created":     datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status":      "pending",
        "title":       title,
        "description": description,
        "code":        code_snippet,
        "target_file": target_file,
    })
    save_proposals(proposals)


def apply_proposal(proposal_id: int) -> dict:
    proposals = load_proposals()
    for p in proposals:
        if p["id"] == proposal_id and p["status"] == "approved":
            target = p.get("target_file", "")
            code   = p.get("code", "")
            if target and code:
                try:
                    with open(os.path.join(_BASE_DIR, target), "w", encoding="utf-8") as f:
                        f.write(code)
                    p["status"] = "applied"
                    save_proposals(proposals)
                    push_alert(f"✅ APPLIED: {p['title']} → {target}")
                    return {"ok": True, "msg": f"Applied to {target}"}
                except Exception as e:
                    return {"ok": False, "msg": str(e)}
            else:
                p["status"] = "applied"
                save_proposals(proposals)
                return {"ok": True, "msg": "Noted (no file to write)"}
    return {"ok": False, "msg": "Not found or not approved"}

# =============================================================================
# BACKGROUND MONITORS
# =============================================================================

def _heartbeat_loop():
    """LAYER 3 — AUTONOMY: runs every HEARTBEAT_INTERVAL seconds."""
    global _last_briefing_hour
    print("[Heartbeat] Autonomous heartbeat started.")
    old_desktop = set(f["name"] for f in get_desktop_files())

    while True:
        try:
            now  = datetime.datetime.now()
            hour = now.hour

            # 1. System health
            mem = get_memory_usage()
            if mem and mem.get("percent", 0) > 90:
                push_alert(f"⚡ RAM critical: {mem['percent']}%!")
            bat = get_battery_status()
            if bat.get("critical"):
                push_alert(f"🔋 Battery critical: {bat['percent']}%! Plug in now.")

            disk = get_disk_usage()
            # Phase 4 — same pseudo-fs filter as get_system_health_score
            # and autonomous_loop.observe_environment; snap squashfs
            # mounts are 100% by design and would push a useless alert
            # every heartbeat.
            _PSEUDO_PREFIXES = ("/snap/", "/var/lib/docker/", "/proc/", "/sys/", "/dev/")
            for mount, d in disk.items():
                if any(mount.startswith(p) for p in _PSEUDO_PREFIXES):
                    continue
                if d.get("percent", 0) > 92:
                    push_alert(f"⚡ Disk almost full: {mount} at {d['percent']}%")

            # 2. Morning/evening briefing
            is_briefing_hour = (6 <= hour <= 10) or (18 <= hour <= 22)
            if is_briefing_hour and hour != _last_briefing_hour:
                try:
                    from memory import get_pattern_context, load_memory, save_briefing
                    pat_ctx  = get_pattern_context()
                    mem_data = load_memory()
                    mem_ctx  = ""
                    if mem_data.get("facts_about_jeevan"):
                        facts   = mem_data["facts_about_jeevan"][-5:]
                        mem_ctx = "Known: " + " | ".join(facts)

                    briefing = _generate_briefing(now, mem_ctx, pat_ctx)
                    save_briefing(briefing)
                    _push_heartbeat_suggestion(briefing["greeting"])
                    _last_briefing_hour = hour
                    push_alert(f"📋 Briefing generated for {now.strftime('%H:%M')}")
                except Exception as e:
                    print(f"[Heartbeat] Briefing error: {e}")

            # 3. Desktop file changes
            new_desktop = set(f["name"] for f in get_desktop_files())
            if new_desktop != old_desktop:
                suggestions = detect_new_files_for_suggestion(old_desktop, new_desktop)
                for s in suggestions:
                    _push_heartbeat_suggestion(s)
                    push_alert(f"👁️ {s[:60]}")
                old_desktop = new_desktop

            # 4. Stale projects
            try:
                from memory import get_stale_projects
                stale = get_stale_projects(days_threshold=7)
                for proj in stale[:2]:
                    _push_heartbeat_suggestion(
                        f"📂 '{proj['project']}' hasn't been touched in {proj['days_ago']} days. "
                        f"Still active? Want to pick it back up?"
                    )
            except Exception:
                pass

            # 5. Save heartbeat
            health = get_system_health_score()
            try:
                atomic_json_write(HEARTBEAT_FILE, {
                    "last_beat":    now.isoformat(),
                    "status":       "alive",
                    "ram_pct":      mem.get("percent") if mem else None,
                    "health_score": health,
                    "version":      AGENT_VERSION,
                })
            except Exception:
                pass

        except Exception as e:
            print(f"[Heartbeat] Error: {e}")

        time.sleep(HEARTBEAT_INTERVAL)


def _generate_briefing(now: datetime.datetime, memory_context: str, pattern_context: str) -> dict:
    hour = now.hour
    if 6 <= hour < 12:
        greeting = f"Morning, {JEEVAN_NAME}. Systems are up and watching."
    elif 12 <= hour < 18:
        greeting = f"Afternoon check-in, {JEEVAN_NAME}. Running clean."
    elif 18 <= hour < 22:
        greeting = f"Evening, {JEEVAN_NAME}. Here's what's been happening."
    else:
        greeting = f"Late-night check, {JEEVAN_NAME}. All systems operational."

    health_lines = []
    mem = get_memory_usage()
    if mem:
        health_lines.append(f"RAM: {mem.get('free_gb', '?')}GB free of {mem.get('total_gb', '?')}GB")
        if mem.get("percent", 0) > 80:
            health_lines.append("⚡ RAM is running high!")
    disk = get_disk_usage()
    for mount, d in disk.items():
        health_lines.append(f"Disk {mount}: {d['free_gb']}GB free of {d['total_gb']}GB")
        if d["percent"] > 90:
            health_lines.append(f"⚡ Disk almost full at {mount}!")
    bat = get_battery_status()
    if bat:
        plug = "charging" if bat.get("plugged") else "on battery"
        health_lines.append(f"Battery: {bat.get('percent', '?')}% ({plug})")

    return {
        "time":         now.strftime("%Y-%m-%d %H:%M"),
        "greeting":     greeting,
        "health":       health_lines,
        "pattern":      pattern_context,
        "memory":       memory_context,
        "generated_at": now.isoformat(),
    }


def _monitor_loop():
    """Background change monitor."""
    print("[Monitor] System change monitor started.")
    while True:
        try:
            old  = _load_snapshot()
            new  = _take_system_snapshot()
            if old:
                old_pkgs = old.get("packages", {})
                new_pkgs = new.get("packages", {})
                old_desk = set(old.get("desktop", []))
                new_desk = set(new.get("desktop", []))
                for name, ver in new_pkgs.items():
                    if name not in old_pkgs:
                        push_alert(f"📦 NEW PACKAGE: {name} {ver}")
                    elif old_pkgs[name] != ver:
                        push_alert(f"📦 UPDATED: {name} {old_pkgs[name]} → {ver}")
                for name in old_pkgs:
                    if name not in new_pkgs:
                        push_alert(f"📦 REMOVED: {name}")
                for f in new_desk - old_desk:
                    push_alert(f"📁 NEW ON DESKTOP: {f}")
            _save_snapshot(new)
        except Exception as e:
            print(f"[Monitor] Error: {e}")
        time.sleep(MONITOR_INTERVAL)


def _take_system_snapshot() -> dict:
    pkgs    = {p["name"]: p["version"] for p in get_installed_packages()}
    desktop = {f["name"] for f in get_desktop_files()}
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "packages":  pkgs,
        "desktop":   list(desktop),
    }


def _load_snapshot() -> dict:
    if os.path.exists(SYSTEM_SNAPSHOT):
        try:
            with open(SYSTEM_SNAPSHOT, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_snapshot(snap: dict):
    atomic_json_write(SYSTEM_SNAPSHOT, snap)


def start_monitor():
    """Start both the change monitor and the autonomous heartbeat loop."""
    # Phase 4.1 — gate through loop_supervisor / config.LOOPS
    from loop_supervisor import loop_enabled
    if not loop_enabled("system_monitor"):
        print("[Monitor] loop disabled by config.LOOPS — not starting")
        return
    t1 = threading.Thread(target=_monitor_loop, daemon=True, name="UltronMonitor")
    t2 = threading.Thread(target=_heartbeat_loop, daemon=True, name="UltronHeartbeat")
    t1.start()
    t2.start()
    print("[Monitor] All background monitors started.")
