"""Tests for vision_perception — distil VisionFrame -> VisionObservation."""
from unittest.mock import MagicMock

import pytest

import vision_perception
from vision_types import VisionFrame, VisionObservation


@pytest.fixture(autouse=True)
def _reset():
    vision_perception._reset_for_test()
    yield
    vision_perception._reset_for_test()


def _frame(ts=10.0):
    return VisionFrame(ts=ts, width=640, height=480, raw=b"\x80" * 100)


def test_observe_returns_none_when_frame_none():
    assert vision_perception.observe(None) is None


def test_observe_with_no_cv2_returns_observation_unavailable(monkeypatch):
    monkeypatch.setattr(vision_perception, "_cv2", None)
    obs = vision_perception.observe(_frame())
    assert isinstance(obs, VisionObservation)
    assert obs.faces == 0
    assert obs.motion is False
    assert obs.person_present is False


def test_observe_uses_face_detector_when_cv2_present(monkeypatch):
    fake_cv2 = MagicMock()
    fake_cv2.IMREAD_GRAYSCALE = 0
    fake_cv2.imdecode.return_value = MagicMock(shape=(480, 640))
    fake_cv2.cvtColor.return_value = MagicMock(shape=(480, 640))
    fake_cv2.COLOR_BGR2GRAY = 6
    fake_detector = MagicMock()
    fake_detector.detectMultiScale.return_value = [(10, 10, 50, 50), (200, 200, 50, 50)]
    fake_cv2.CascadeClassifier.return_value = fake_detector
    monkeypatch.setattr(vision_perception, "_cv2", fake_cv2)
    monkeypatch.setattr(vision_perception, "_frame_to_array",
                        lambda f: MagicMock(shape=(480, 640, 3), mean=lambda: 128.0))
    obs = vision_perception.observe(_frame())
    assert obs.faces == 2
    assert obs.person_present is True


def test_observe_brightness_from_pixel_mean(monkeypatch):
    fake_cv2 = MagicMock()
    fake_cv2.CascadeClassifier.return_value.detectMultiScale.return_value = []
    fake_cv2.cvtColor.return_value = MagicMock(shape=(480, 640))
    arr = MagicMock(shape=(480, 640, 3))
    arr.mean = MagicMock(return_value=204.0)  # 204/255 = 0.8
    monkeypatch.setattr(vision_perception, "_cv2", fake_cv2)
    monkeypatch.setattr(vision_perception, "_frame_to_array", lambda f: arr)
    obs = vision_perception.observe(_frame())
    assert 0.79 < obs.brightness < 0.81


def test_observe_detects_motion_across_frames(monkeypatch):
    fake_cv2 = MagicMock()
    fake_cv2.CascadeClassifier.return_value.detectMultiScale.return_value = []
    fake_cv2.cvtColor.side_effect = lambda f, code: f  # passthrough
    # Two arrays with different mean -> motion
    arr1 = MagicMock(); arr1.mean = MagicMock(return_value=100.0); arr1.shape = (480, 640)
    arr2 = MagicMock(); arr2.mean = MagicMock(return_value=200.0); arr2.shape = (480, 640)
    monkeypatch.setattr(vision_perception, "_cv2", fake_cv2)

    seq = iter([arr1, arr2])
    monkeypatch.setattr(vision_perception, "_frame_to_array", lambda f: next(seq))

    obs1 = vision_perception.observe(_frame(ts=1.0))
    obs2 = vision_perception.observe(_frame(ts=2.0))
    assert obs1.motion is False  # no prior frame
    assert obs2.motion is True   # big delta vs frame 1


def test_observe_exception_returns_safe_observation(monkeypatch):
    fake_cv2 = MagicMock()
    fake_cv2.CascadeClassifier.side_effect = RuntimeError("missing cascade")
    monkeypatch.setattr(vision_perception, "_cv2", fake_cv2)
    monkeypatch.setattr(vision_perception, "_frame_to_array",
                        lambda f: MagicMock(shape=(480, 640, 3), mean=lambda: 100.0))
    obs = vision_perception.observe(_frame())
    assert isinstance(obs, VisionObservation)
    assert obs.faces == 0
