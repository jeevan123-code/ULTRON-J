"""activity_tracker.py — Background mouse/keyboard activity monitor.

pynput's keyboard hook works reliably here, but its mouse low-level hook
silently fails to deliver events in this Windows console-process setup
(``Listener.is_alive()`` returns True but ``on_move``/``on_click`` never
fire). To keep mouse_pos / last_mouse_move accurate, run a pyautogui
position-polling fallback alongside the pynput listeners. The pynput
mouse Listener is still registered so click events can land if the hook
ever delivers them; module-level references prevent garbage collection.
"""
import time
import threading

_state = {
    "last_mouse_move": 0.0,
    "last_click":      0.0,
    "last_key":        0.0,
    "mouse_pos":       (0, 0),
    "running":         False,
}
_lock = threading.Lock()

# Module-level references so the Listener objects (and their internal
# Windows hook handles) are not garbage collected.
_listeners: list = []


def get_activity() -> dict:
    with _lock:
        now = time.time()
        last_any = max(
            _state["last_mouse_move"],
            _state["last_click"],
            _state["last_key"],
        )
        return {
            **_state,
            "idle_seconds": now - last_any if last_any > 0 else 0,
        }


def _poll_mouse_position():
    """Fallback: poll pyautogui.position() ~2.5 Hz. Updates mouse_pos and
    last_mouse_move whenever the cursor moves. Independent of any
    pynput / Windows-hook plumbing."""
    try:
        import pyautogui
    except Exception:
        return
    last_xy = None
    while True:
        try:
            x, y = pyautogui.position()
        except Exception:
            time.sleep(1.0)
            continue
        if last_xy != (x, y):
            with _lock:
                _state["mouse_pos"] = (x, y)
                _state["last_mouse_move"] = time.time()
            last_xy = (x, y)
        time.sleep(0.4)


def start_tracker():
    if _state["running"]:
        return
    try:
        from pynput import mouse, keyboard

        def on_move(x, y):
            with _lock:
                _state["last_mouse_move"] = time.time()
                _state["mouse_pos"] = (x, y)

        def on_click(x, y, button, pressed):
            if pressed:
                with _lock:
                    _state["last_click"] = time.time()

        def on_key(key):
            with _lock:
                _state["last_key"] = time.time()

        ml = mouse.Listener(on_move=on_move, on_click=on_click, daemon=True)
        kl = keyboard.Listener(on_press=on_key, daemon=True)
        ml.start()
        kl.start()
        _listeners.extend([ml, kl])

        # pyautogui polling fallback — runs forever in a daemon thread.
        poll_thr = threading.Thread(
            target=_poll_mouse_position, daemon=True, name="activity_mouse_poll"
        )
        poll_thr.start()
        _listeners.append(poll_thr)

        _state["running"] = True
    except Exception as e:
        print(f"[ActivityTracker] failed: {e}")
        return False
    return True
