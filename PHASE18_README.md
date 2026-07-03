# Phase 18 — Continuous Vision Loop (Tier 2 embodiment)

Phase 9 gave one-shot `look` snapshots. Phase 18 makes vision a CONTINUOUS
awareness loop: capture → perceive → diff → emit an EVENT on meaningful
transitions, so Ultron can react to the room proactively.

## `vision_stream.py`
- `detect_events(prev, curr)` — PURE: person_arrived / person_left /
  motion_started / went_dark / lit_up / new_faces. (A face gain that is really
  an arrival is not double-reported.)
- `tick()` — one capture→perceive→diff→emit cycle. Capture/perceive/emit are
  injectable seams (`_capture`, `_perceive`, `set_event_handler`).
- `start(interval)/stop()` — background loop (opt-in).

## Hardware seam (honest)
Capture uses `vision_capture.get_latest_frame()` → OpenCV (`cv2`), a **soft
dependency**. No camera / no cv2 ⇒ `tick()` returns `[]`, never crashes. The
event logic and controller are fully unit-tested with mocked frames; the live
webcam path needs real hardware to exercise end-to-end.

## Wiring
The loop is opt-in (`start()`), not auto-started, and emits to a registered
handler. A natural next hook: feed `person_arrived`/`person_left` into
`room_awareness` so presence (not just voice) informs Phase 5d privacy — left as
a deliberate follow-up.

## Tests (8)
`tests/test_vision_stream.py` — event matrix + controller with mocked seams.
