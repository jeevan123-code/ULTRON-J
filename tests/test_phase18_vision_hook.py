"""Phase 18 wiring — the continuous vision loop needs a production starter.

vision_stream shipped with start()/stop()/set_event_handler() and no caller, so
the loop never ran and its events had nowhere to go. This hook is the seam
app.py calls at startup, mirroring phase5g_implicit_hook.

The camera driver is a real hardware dependency (cv2 is not installed here);
the hook must therefore degrade to "did not start" rather than raise.
"""
import pytest

import phase18_vision_hook as hook
import vision_stream


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    started = []
    monkeypatch.setattr(vision_stream, "start",
                        lambda interval=5.0: started.append(interval) or True)
    monkeypatch.setattr(vision_stream, "stop", lambda: started.append("stop"))
    vision_stream.set_event_handler(None)
    yield started
    vision_stream.set_event_handler(None)


def test_does_not_start_when_flag_is_off(monkeypatch, _isolate):
    monkeypatch.delenv("ULTRON_PHASE18_ENABLED", raising=False)
    assert hook.start() is False
    assert _isolate == []


def test_starts_when_flag_is_on(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE18_ENABLED", "1")
    assert hook.start() is True
    assert _isolate == [hook.DEFAULT_INTERVAL]


def test_interval_is_configurable_not_hardcoded(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE18_ENABLED", "1")
    monkeypatch.setenv("ULTRON_PHASE18_INTERVAL", "12.5")
    hook.start()
    assert _isolate == [12.5]


def test_bad_interval_falls_back_to_default(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE18_ENABLED", "1")
    monkeypatch.setenv("ULTRON_PHASE18_INTERVAL", "not-a-number")
    hook.start()
    assert _isolate == [hook.DEFAULT_INTERVAL]


def test_events_reach_the_user(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE18_ENABLED", "1")
    pushed = []
    monkeypatch.setattr(hook, "_notify", lambda msg: pushed.append(msg))
    hook.start()
    # The hook must have registered a handler on vision_stream.
    vision_stream._emit(vision_stream.VisionEvent(ts=0.0, kind="motion", detail={"where": "desk"}))
    assert pushed and "motion" in pushed[0]


def test_missing_camera_backend_does_not_raise(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE18_ENABLED", "1")
    monkeypatch.setattr(
        vision_stream, "start",
        lambda interval=5.0: (_ for _ in ()).throw(ImportError("No module named 'cv2'")))
    assert hook.start() is False  # degraded, not crashed


def test_notify_failure_does_not_break_the_vision_loop(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE18_ENABLED", "1")
    monkeypatch.setattr(hook, "_notify",
                        lambda msg: (_ for _ in ()).throw(RuntimeError("bus down")))
    hook.start()
    vision_stream._emit(vision_stream.VisionEvent(ts=0.0, kind="motion", detail={}))  # must not raise


def test_stop_is_available(monkeypatch, _isolate):
    monkeypatch.setenv("ULTRON_PHASE18_ENABLED", "1")
    hook.start()
    hook.stop()
    assert "stop" in _isolate
