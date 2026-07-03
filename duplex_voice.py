"""Phase 19 — full-duplex voice controller (Tier 2 embodiment).

Today's voice loop is half-duplex: two SpeechRecognition instances switched by
state, and Ultron can't be interrupted mid-sentence. This module is the CONTROL
LOGIC for a full-duplex experience:

  * barge-in — the user can talk over Ultron; that stops TTS and starts
    listening immediately.
  * no wake word inside a conversation — after Ultron finishes speaking it keeps
    listening for a follow-up until a silence timeout closes the conversation.

The controller is a PURE, deterministic state machine that emits ACTIONS
("stop_tts", "start_listening", ...). A thin audio DRIVER (not in this module)
performs those actions against the real STT/TTS backend — that driver is the
hardware-dependent seam; the decision logic here is fully unit-tested.
"""
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class State(str, Enum):
    IDLE = "idle"            # waiting for a wake word
    LISTENING = "listening"  # capturing user speech
    THINKING = "thinking"    # LLM is producing a response
    SPEAKING = "speaking"    # TTS is playing


# Actions the driver must perform (returned from every transition).
ACT_START_LISTEN = "start_listening"
ACT_STOP_LISTEN = "stop_listening"
ACT_START_TTS = "start_tts"
ACT_STOP_TTS = "stop_tts"
ACT_PROCESS = "process_utterance"
ACT_CANCEL_THINK = "cancel_thinking"
ACT_END_CONVERSATION = "end_conversation"


@dataclass
class DuplexController:
    """Deterministic full-duplex conversation state machine."""
    conversation_window: float = 8.0   # secs of follow-up listening w/o wake word
    state: State = State.IDLE
    _conversation_active: bool = field(default=False, repr=False)

    # ── external events ──────────────────────────────────────────────────────
    def on_wake(self) -> List[str]:
        """Wake word heard while idle -> start listening + open a conversation."""
        if self.state != State.IDLE:
            return []
        self._conversation_active = True
        self.state = State.LISTENING
        return [ACT_START_LISTEN]

    def on_speech_final(self, text: str) -> List[str]:
        """A complete user utterance was captured while listening."""
        if self.state != State.LISTENING:
            return []
        if not (text or "").strip():
            # empty utterance -> keep listening
            return []
        self.state = State.THINKING
        return [ACT_STOP_LISTEN, ACT_PROCESS]

    def on_response_ready(self) -> List[str]:
        """LLM produced a response -> speak it."""
        if self.state != State.THINKING:
            return []
        self.state = State.SPEAKING
        return [ACT_START_TTS]

    def on_tts_finished(self) -> List[str]:
        """TTS finished. In an active conversation, listen again with NO wake
        word; otherwise fall back to idle."""
        if self.state != State.SPEAKING:
            return []
        if self._conversation_active:
            self.state = State.LISTENING
            return [ACT_START_LISTEN]
        self.state = State.IDLE
        return []

    def on_user_interrupt(self) -> List[str]:
        """Barge-in: the user started talking. This is the core duplex move."""
        if self.state == State.SPEAKING:
            self.state = State.LISTENING
            return [ACT_STOP_TTS, ACT_START_LISTEN]
        if self.state == State.THINKING:
            self.state = State.LISTENING
            return [ACT_CANCEL_THINK, ACT_START_LISTEN]
        return []

    def on_silence(self) -> List[str]:
        """Silence timeout while listening -> close the conversation."""
        if self.state != State.LISTENING:
            return []
        self._conversation_active = False
        self.state = State.IDLE
        return [ACT_STOP_LISTEN, ACT_END_CONVERSATION]

    # ── introspection ────────────────────────────────────────────────────────
    @property
    def conversation_active(self) -> bool:
        return self._conversation_active

    def snapshot(self) -> Dict[str, Any]:
        return {"state": self.state.value,
                "conversation_active": self._conversation_active}
