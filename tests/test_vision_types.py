"""Tests for vision_types — VisionFrame + VisionObservation dataclasses."""
import pytest

from vision_types import VisionFrame, VisionObservation


def test_vision_frame_construction():
    f = VisionFrame(ts=100.0, width=640, height=480, raw=b"\x00" * 10)
    assert f.ts == 100.0
    assert f.width == 640
    assert f.height == 480
    assert len(f.raw) == 10


def test_vision_frame_size_property():
    f = VisionFrame(ts=1.0, width=320, height=240, raw=b"")
    assert f.size == (320, 240)


def test_vision_observation_defaults():
    obs = VisionObservation(ts=100.0)
    assert obs.faces == 0
    assert obs.motion is False
    assert obs.brightness == 0.0
    assert obs.person_present is False


def test_vision_observation_to_dict_roundtrip():
    obs = VisionObservation(
        ts=10.0, faces=2, motion=True,
        brightness=0.6, person_present=True,
    )
    d = obs.to_dict()
    back = VisionObservation.from_dict(d)
    assert back == obs


def test_brightness_clamped_to_zero_one():
    obs = VisionObservation(ts=1.0, brightness=2.0)
    assert obs.brightness == 1.0
    obs2 = VisionObservation(ts=1.0, brightness=-0.3)
    assert obs2.brightness == 0.0
