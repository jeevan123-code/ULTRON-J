"""
sleep_guard.py — Keep Ultron-J alive forever. BEYOND JARVIS.

Problems solved:
1. PC Sleep kills Ultron        → Prevent sleep while Ultron runs
2. Ultron crashes               → Watchdog restarts it automatically
3. Need 2 terminals             → Single launcher script handles everything
4. Server goes offline silently → Health pinger with alert

Usage:
    python sleep_guard.py              # Launches Ultron + watchdog + sleep prevention
    python sleep_guard.py --status     # Check if Ultron is alive
    python sleep_guard.py --restart    # Force restart

How it works:
- Prevents OS sleep using platform-specific APIs (no third-party needed)
- Watchdog: pings /health every 30s, restarts if dead
- Single entry point: start everything from one terminal
"""

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
_GUARD_LOG   = os.path.join(_BASE_DIR, "sleep_guard.log")
_STATUS_FILE = os.path.join(_BASE_DIR, "ultron_status.json")
_PID_FILE    = os.path.join(_BASE_DIR, "ultron.pid")
_PLATFORM    = platform.system()

_ultron_process: subprocess.Popen = None
_guard_running  = True


# =============================================================================
# SLEEP PREVENTION
# =============================================================================

class SleepPreventer:
    """Prevent OS from sleeping while Ultron is running."""

    def __init__(self):
        self._active  = False
        self._thread  = None
        self._handle  = None   # Windows only

    def start(self):
        if self._active:
            return
        self._active = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="sleep_preventer")
        self._thread.start()
        _log(f"[SleepGuard] Sleep prevention started on {_PLATFORM}")

    def stop(self):
        self._active = False
        if _PLATFORM == "Windows":
            self._windows_allow_sleep()
        _log("[SleepGuard] Sleep prevention stopped")

    def _run(self):
        if _PLATFORM == "Windows":
            self._windows_prevent_sleep()
        elif _PLATFORM == "Darwin":
            self._macos_prevent_sleep()
        elif _PLATFORM == "Linux":
            self._linux_prevent_sleep()

    def _windows_prevent_sleep(self):
        """Use SetThreadExecutionState to prevent sleep."""
        try:
            import ctypes
            ES_CONTINUOUS       = 0x80000000
            ES_SYSTEM_REQUIRED  = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002
            while self._active:
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                )
                time.sleep(30)
        except Exception as e:
            _log(f"[SleepGuard] Windows sleep prevention error: {e}")

    def _windows_allow_sleep(self):
        try:
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except Exception:
            pass

    def _macos_prevent_sleep(self):
        """Use caffeinate on macOS."""
        try:
            proc = subprocess.Popen(["caffeinate", "-i"],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
            while self._active:
                time.sleep(10)
            proc.terminate()
        except FileNotFoundError:
            _log("[SleepGuard] caffeinate not found — sleep prevention unavailable on macOS")
        except Exception as e:
            _log(f"[SleepGuard] macOS sleep prevention error: {e}")

    def _linux_prevent_sleep(self):
        """Use xdg-screensaver or systemd inhibit on Linux."""
        try:
            proc = subprocess.Popen(
                ["systemd-inhibit", "--what=sleep:idle", "--who=Ultron-J",
                 "--why=Ultron is running", "--mode=block", "sleep", "infinity"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            while self._active:
                time.sleep(30)
            proc.terminate()
        except FileNotFoundError:
            # Fallback: simulate activity with xdotool
            while self._active:
                try:
                    subprocess.run(["xdotool", "key", "shift"],
                                   capture_output=True, timeout=5)
                except Exception:
                    pass
                time.sleep(55)


# =============================================================================
# WATCHDOG
# =============================================================================

class Watchdog:
    """
    Monitor Ultron-J process. Restart if it dies.
    Also pings /health endpoint to detect hangs.
    """

    def __init__(self, app_cmd: list, health_url: str = "http://localhost:5000/health",
                 check_interval: int = 30, max_restarts: int = 10):
        self.app_cmd        = app_cmd
        self.health_url     = health_url
        self.check_interval = check_interval
        self.max_restarts   = max_restarts
        self._restart_count = 0
        self._start_time    = None

    def launch(self) -> subprocess.Popen:
        global _ultron_process
        _log(f"[Watchdog] Launching: {' '.join(self.app_cmd)}")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            self.app_cmd,
            stdout=open(os.path.join(_BASE_DIR, "ultron_stdout.log"), "a"),
            stderr=open(os.path.join(_BASE_DIR, "ultron_stderr.log"), "a"),
            env=env,
            cwd=_BASE_DIR,
        )
        _ultron_process = proc
        self._start_time = datetime.now()
        # Write PID
        with open(_PID_FILE, "w") as f:
            f.write(str(proc.pid))
        _write_status("running", proc.pid)
        _log(f"[Watchdog] Launched PID {proc.pid}")
        return proc

    def is_healthy(self) -> bool:
        """Ping the health endpoint."""
        try:
            import urllib.request
            with urllib.request.urlopen(self.health_url, timeout=5) as r:
                return r.status == 200
        except Exception:
            return False

    def run(self):
        """Main watchdog loop. Returns only when guard is stopped."""
        global _guard_running
        proc = self.launch()
        # Give it time to start
        time.sleep(8)

        consecutive_health_fails = 0

        while _guard_running:
            # Check if process is alive
            if proc.poll() is not None:
                exit_code = proc.returncode
                _log(f"[Watchdog] Ultron died (exit {exit_code}). Restarting...")
                _write_status("restarting", None)

                if self._restart_count >= self.max_restarts:
                    _log(f"[Watchdog] Max restarts ({self.max_restarts}) reached. Giving up.")
                    _write_status("crashed", None)
                    break

                self._restart_count += 1
                time.sleep(3)
                proc = self.launch()
                time.sleep(8)
                consecutive_health_fails = 0
                continue

            # Health check
            if not self.is_healthy():
                consecutive_health_fails += 1
                _log(f"[Watchdog] Health check failed ({consecutive_health_fails})")
                if consecutive_health_fails >= 3:
                    _log("[Watchdog] 3 consecutive health fails — killing and restarting")
                    proc.kill()
                    time.sleep(2)
                    self._restart_count += 1
                    proc = self.launch()
                    time.sleep(8)
                    consecutive_health_fails = 0
            else:
                consecutive_health_fails = 0
                _write_status("healthy", proc.pid)

            time.sleep(self.check_interval)

    def stop_process(self):
        global _ultron_process
        if _ultron_process and _ultron_process.poll() is None:
            _log("[Watchdog] Stopping Ultron-J...")
            _ultron_process.terminate()
            try:
                _ultron_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _ultron_process.kill()
            _write_status("stopped", None)
            if os.path.exists(_PID_FILE):
                os.remove(_PID_FILE)


# =============================================================================
# REAL-TIME HEARTBEAT (replaces 5-min polling)
# =============================================================================

class RealtimeHeartbeat:
    """
    Event-driven heartbeat — fires immediately on:
    - File system changes
    - Clipboard changes
    - High CPU/RAM
    - Network change
    Instead of waiting 5 minutes.
    """

    def __init__(self, notify_fn=None, min_interval: float = 2.0):
        self._notify      = notify_fn or (lambda msg: print(f"[Heartbeat] {msg}"))
        self._min_interval = min_interval
        self._last_fired  = 0
        self._running     = False
        self._events      = []
        self._lock        = threading.Lock()
        self._event_ready = threading.Event()

    def push_event(self, event_type: str, data: dict = None):
        """Push an event — triggers heartbeat if enough time has passed."""
        with self._lock:
            self._events.append({
                "type": event_type,
                "data": data or {},
                "ts":   datetime.now().isoformat(),
            })
        self._event_ready.set()

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name="realtime_heartbeat").start()
        _log("[Heartbeat] Real-time heartbeat started")

    def stop(self):
        self._running = False
        self._event_ready.set()

    def _loop(self):
        while self._running:
            triggered = self._event_ready.wait(timeout=60)   # max 60s between heartbeats
            if not self._running:
                break
            self._event_ready.clear()
            now = time.time()
            if now - self._last_fired < self._min_interval:
                continue
            self._last_fired = now
            with self._lock:
                events = list(self._events)
                self._events.clear()
            if events or triggered:
                try:
                    self._notify(events)
                except Exception as e:
                    _log(f"[Heartbeat] Notify error: {e}")


# =============================================================================
# STATUS / LOG HELPERS
# =============================================================================

def _log(msg: str):
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    print(line.strip())
    try:
        with open(_GUARD_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


def _write_status(state: str, pid):
    try:
        with open(_STATUS_FILE, "w") as f:
            json.dump({
                "state":      state,
                "pid":        pid,
                "updated_at": datetime.now().isoformat(),
                "platform":   _PLATFORM,
            }, f, indent=2)
    except Exception:
        pass


def get_status() -> dict:
    if os.path.exists(_STATUS_FILE):
        try:
            with open(_STATUS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"state": "unknown"}


def get_pid() -> int:
    if os.path.exists(_PID_FILE):
        try:
            return int(open(_PID_FILE).read().strip())
        except Exception:
            pass
    return -1


# =============================================================================
# MAIN — single-command launcher
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Ultron-J Sleep Guard & Watchdog")
    parser.add_argument("--status",   action="store_true", help="Show Ultron status")
    parser.add_argument("--restart",  action="store_true", help="Restart Ultron")
    parser.add_argument("--stop",     action="store_true", help="Stop Ultron")
    parser.add_argument("--port",     default="5000",      help="Flask port")
    parser.add_argument("--no-sleep-guard", action="store_true", help="Disable sleep prevention")
    args = parser.parse_args()

    if args.status:
        s = get_status()
        print(json.dumps(s, indent=2))
        return

    if args.stop:
        pid = get_pid()
        if pid > 0:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"Sent SIGTERM to PID {pid}")
            except ProcessLookupError:
                print("Process not found")
        return

    python_exe = sys.executable
    app_script = os.path.join(_BASE_DIR, "app.py")
    app_cmd    = [python_exe, app_script]

    if args.restart:
        pid = get_pid()
        if pid > 0:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(2)
            except ProcessLookupError:
                pass

    # Sleep preventer
    preventer = SleepPreventer()
    if not args.no_sleep_guard:
        preventer.start()

    # Watchdog
    watchdog = Watchdog(
        app_cmd=app_cmd,
        health_url=f"http://localhost:{args.port}/health",
    )

    def _handle_exit(sig, frame):
        global _guard_running
        _log("[SleepGuard] Shutdown signal received")
        _guard_running = False
        preventer.stop()
        watchdog.stop_process()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    _log("=" * 60)
    _log("  Ultron-J Sleep Guard + Watchdog")
    _log(f"  Platform: {_PLATFORM}")
    _log(f"  App: {app_script}")
    _log(f"  Sleep prevention: {'ON' if not args.no_sleep_guard else 'OFF'}")
    _log("=" * 60)

    watchdog.run()


if __name__ == "__main__":
    main()
