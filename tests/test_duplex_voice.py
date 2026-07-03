"""Tests for duplex_voice — full-duplex conversation state machine."""
import pytest

from duplex_voice import (
    DuplexController, State,
    ACT_START_LISTEN, ACT_STOP_LISTEN, ACT_START_TTS, ACT_STOP_TTS,
    ACT_PROCESS, ACT_CANCEL_THINK, ACT_END_CONVERSATION,
)


def test_happy_path_turn():
    c = DuplexController()
    assert c.on_wake() == [ACT_START_LISTEN]
    assert c.state == State.LISTENING
    assert c.on_speech_final("what's the weather") == [ACT_STOP_LISTEN, ACT_PROCESS]
    assert c.state == State.THINKING
    assert c.on_response_ready() == [ACT_START_TTS]
    assert c.state == State.SPEAKING


def test_no_wake_word_needed_for_followup():
    c = DuplexController()
    c.on_wake(); c.on_speech_final("hi"); c.on_response_ready()
    # after speaking, conversation stays open -> listen again with no wake word
    assert c.on_tts_finished() == [ACT_START_LISTEN]
    assert c.state == State.LISTENING


def test_barge_in_stops_tts_and_listens():
    c = DuplexController()
    c.on_wake(); c.on_speech_final("tell me a long story"); c.on_response_ready()
    assert c.state == State.SPEAKING
    assert c.on_user_interrupt() == [ACT_STOP_TTS, ACT_START_LISTEN]
    assert c.state == State.LISTENING


def test_barge_in_while_thinking_cancels():
    c = DuplexController()
    c.on_wake(); c.on_speech_final("hmm")
    assert c.state == State.THINKING
    assert c.on_user_interrupt() == [ACT_CANCEL_THINK, ACT_START_LISTEN]
    assert c.state == State.LISTENING


def test_silence_closes_conversation():
    c = DuplexController()
    c.on_wake()
    assert c.on_silence() == [ACT_STOP_LISTEN, ACT_END_CONVERSATION]
    assert c.state == State.IDLE
    assert c.conversation_active is False
    # after conversation closed, tts_finished path would go idle
    c2 = DuplexController()
    c2.on_wake(); c2.on_speech_final("x"); c2.on_response_ready()
    c2._conversation_active = False
    assert c2.on_tts_finished() == []
    assert c2.state == State.IDLE


def test_wake_ignored_when_not_idle():
    c = DuplexController()
    c.on_wake()
    assert c.on_wake() == []          # already listening


def test_empty_utterance_keeps_listening():
    c = DuplexController()
    c.on_wake()
    assert c.on_speech_final("   ") == []
    assert c.state == State.LISTENING


def test_events_are_ignored_in_wrong_state():
    c = DuplexController()
    # idle: nothing should happen for these
    assert c.on_speech_final("x") == []
    assert c.on_response_ready() == []
    assert c.on_tts_finished() == []
    assert c.on_user_interrupt() == []
    assert c.on_silence() == []
    assert c.state == State.IDLE
