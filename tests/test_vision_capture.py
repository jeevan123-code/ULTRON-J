"""Tests for vision_capture — webcam abstraction with soft cv2 dep."""
from unittest.mock import MagicMock

import pytest

import vision_capture
from vision_types import VisionFrame


@pytest.fixture(autouse=True)
def _reset():
    vision_capture._reset_for_test()
    yield
    vision_capture._reset_for_test()


def test_is_available_false_when_cv2_missing(monkeypatch):
    monkeypatch.setattr(vision_capture, "_cv2", None)
    assert vision_capture.is_available() is False


def test_is_available_true_when_cv2_present(monkeypatch):
    monkeypatch.setattr(vision_capture, "_cv2", object())
    assert vision_capture.is_available() is True


def test_get_latest_frame_returns_none_when_cv2_missing(monkeypatch):
    monkeypatch.setattr(vision_capture, "_cv2", None)
    assert vision_capture.get_latest_frame() is None


def test_get_latest_frame_returns_frame_when_capture_ok(monkeypatch):
    fake_cv2 = MagicMock()
    fake_cap = MagicMock()
    fake_cap.read.return_value = (True, MagicMock(shape=(480, 640, 3), tobytes=lambda: b"\x00" * 8))
    fake_cv2.VideoCapture.return_value = fake_cap
    monkeypatch.setattr(vision_capture, "_cv2", fake_cv2)
    monkeypatch.setattr(vision_capture, "_now", lambda: 42.0)

    frame = vision_capture.get_latest_frame()
    assert isinstance(frame, VisionFrame)
    assert frame.ts == 42.0
    assert frame.width == 640
    assert frame.height == 480


def test_get_latest_frame_returns_none_when_read_fails(monkeypatch):
    fake_cv2 = MagicMock()
    fake_cap = MagicMock()
    fake_cap.read.return_value = (False, None)
    fake_cv2.VideoCapture.return_value = fake_cap
    monkeypatch.setattr(vision_capture, "_cv2", fake_cv2)
    assert vision_capture.get_latest_frame() is None


def test_get_latest_frame_swallows_exception(monkeypatch):
    fake_cv2 = MagicMock()
    fake_cv2.VideoCapture.side_effect = RuntimeError("no camera")
    monkeypatch.setattr(vision_capture, "_cv2", fake_cv2)
    assert vision_capture.get_latest_frame() is None
