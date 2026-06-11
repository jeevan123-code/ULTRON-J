# Phase 9 — Vision

Status: SHIPPED on branch `phase9-vision`.

## What Phase 9 Builds

JARVIS sees what Tony sees. Phase 9 gives ULTRON the same primitive:

```python
from chain_executor import execute_chain
from intent_types import ExecutionPlan

execute_chain(ExecutionPlan(
    steps=[
        {"action": "look"},
        {"action": "alert", "args": {
            "message": "Sir, {{prev.faces}} person(s) at the desk."
        }, "continue_on_failure": True},
    ],
    pre_checks=[], rationale="check who's here",
))
```

One webcam grab → distilled `VisionObservation` → flows directly into
the next step via `{{prev.faces}}` interpolation. Chain steps can now
include vision as a first-class primitive.

## Modules

| File | Tests | Purpose |
|---|---:|---|
| `vision_types.py` | 5 | `VisionFrame` + `VisionObservation` dataclasses |
| `vision_capture.py` | 6 | webcam grab via cv2 (soft dep); returns `None` when unavailable |
| `vision_perception.py` | 6 | Haar-cascade face detector + between-frame brightness delta for motion |
| `chain_executor.py` (extended) | 3 | new `look` action wires capture → perception into a chain step |

**20 new tests**, zero regression on the 1065-test Phase 8 baseline.

## Soft cv2 dependency

`cv2` (OpenCV) is the canonical implementation but is **not** added to
`requirements.txt`. The vision modules degrade silently when it's
missing:

- `vision_capture.is_available()` returns `False`.
- `get_latest_frame()` returns `None`.
- `vision_perception.observe(None)` returns `None`.
- A chain `look` step returns `{ok: False, error: "no_frame"}`.

For real production use, install OpenCV:

```bash
.venv/bin/pip install opencv-python
```

(~100 MB. Adds numpy as a transitive dep — already pinned.) Without it,
every other phase still works.

## What perception sees

| Field | Source | Type |
|---|---|---|
| `faces` | Haar cascade `haarcascade_frontalface_default.xml` | int |
| `motion` | `\|brightness_t − brightness_{t-1}\| ≥ 0.15` | bool |
| `brightness` | mean pixel value, normalised to [0, 1] | float |
| `person_present` | `faces > 0` | bool |

No GPU, no heavy models. The face detector is OpenCV's bundled Haar
cascade — adequate for "is someone in front of the camera" without a
neural-net dependency. Higher-quality detection (DNN, MediaPipe) can
slot in later by swapping the `_dispatch_look` implementation.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_vision_types.py \
    tests/test_vision_capture.py \
    tests/test_vision_perception.py \
    tests/test_phase9_look_action.py -v
```

## What's next

- Phase 10: plan_builder that turns "Jarvis, who's at the door?" into
  the `[look, alert]` chain above without hand-building the plan.
- DNN-based detector for better accuracy (MediaPipe / YOLO-nano).
- Frame caching so back-to-back `look` calls in the same chain re-use
  one grab instead of re-opening the camera.
