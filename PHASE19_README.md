# Phase 19 — Full-Duplex Voice Controller (Tier 2 embodiment)

The current voice loop is half-duplex (two SR instances switched by state, no
interrupting Ultron mid-sentence). Phase 19 is the CONTROL LOGIC for a
full-duplex experience:

- **Barge-in** — the user can talk over Ultron; `on_user_interrupt()` while
  SPEAKING emits `stop_tts` + `start_listening` immediately (while THINKING it
  cancels the pending response).
- **No wake word inside a conversation** — after TTS finishes, if the
  conversation window is open, it listens again with no wake word; a silence
  timeout closes the conversation back to IDLE.

## `duplex_voice.DuplexController`
A PURE, deterministic state machine (IDLE → LISTENING → THINKING → SPEAKING).
Every event returns a list of ACTIONS for a driver to perform. No audio in this
module.

## Hardware seam (honest)
A thin audio DRIVER (STT stream + interruptible TTS) must perform the emitted
actions against the real backend — that driver is the hardware/real-time
dependency and is where a live mic/streaming-TTS integration plugs in. The
decision logic (barge-in, follow-up, timeouts) is fully unit-tested here; the
end-to-end latency/streaming behaviour needs live audio to validate.

## Tests (8)
`tests/test_duplex_voice.py` — happy path, barge-in (speaking + thinking),
follow-up without wake word, silence close, wrong-state guards.
