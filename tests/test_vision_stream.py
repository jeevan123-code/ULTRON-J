"""Tests for vision_stream — continuous event-triggered vision (no webcam needed)."""
import pytest

import vision_stream as vs
from vision_types import VisionObservation


@pytest.fixture(autouse=True)
def _isolate():
    vs._reset_for_test()
    yield
    vs._reset_for_test()


def _obs(person=False, motion=False, brightness=0.5, faces=0, ts=1.0):
    return VisionObservation(ts=ts, faces=faces, motion=motion,
                             brightness=brightness, person_present=person)


# ── pure detect_events ─────────────────────────────────────────────────────
def test_person_arrival_and_departure():
    e1 = vs.detect_events(None, _obs(person=True, faces=1))
    assert [e.kind for e in e1] == ["person_arrived"]
    e2 = vs.detect_events(_obs(person=True), _obs(person=False))
    assert [e.kind for e in e2] == ["person_left"]


def test_no_spurious_left_on_first_observation():
    assert vs.detect_events(None, _obs(person=False)) == []


def test_motion_started_once():
    assert [e.kind for e in vs.detect_events(_obs(motion=False), _obs(motion=True))] \
        == ["motion_started"]
    assert vs.detect_events(_obs(motion=True), _obs(motion=True)) == []


def test_brightness_transitions():
    dark = vs.detect_events(_obs(brightness=0.5), _obs(brightness=0.1))
    assert any(e.kind == "went_dark" for e in dark)
    lit = vs.detect_events(_obs(brightness=0.1), _obs(brightness=0.6))
    assert any(e.kind == "lit_up" for e in lit)


def test_new_faces():
    ev = vs.detect_events(_obs(faces=1, person=True), _obs(faces=3, person=True))
    assert any(e.kind == "new_faces" and e.detail["to"] == 3 for e in ev)


def test_none_current_yields_nothing():
    assert vs.detect_events(_obs(), None) == []


# ── controller tick with mocked seams ──────────────────────────────────────
def test_tick_emits_and_calls_handler(monkeypatch):
    frames = iter([object(), object()])
    obses = iter([_obs(person=False, ts=1.0), _obs(person=True, faces=1, ts=2.0)])
    monkeypatch.setattr(vs, "_capture", lambda: next(frames))
    monkeypatch.setattr(vs, "_perceive", lambda f: next(obses))
    got = []
    vs.set_event_handler(lambda e: got.append(e["kind"]))

    assert vs.tick() == []                       # first obs: nobody present
    events = vs.tick()                           # person arrives
    assert [e.kind for e in events] == ["person_arrived"]
    assert got == ["person_arrived"]


def test_tick_no_frame_is_safe(monkeypatch):
    monkeypatch.setattr(vs, "_capture", lambda: None)
    monkeypatch.setattr(vs, "_perceive", lambda f: None)
    assert vs.tick() == []                        # no camera -> no crash
