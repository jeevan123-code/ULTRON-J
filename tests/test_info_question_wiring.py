"""/ask must not hand an info question to the action orchestrator.

info_question is unit-tested in test_info_question.py; this covers the GLUE in
app.py — the intercept at app.py:748 that returned the orchestrator's raw
search output as the answer, bypassing the LLM entirely.

The orchestrator stub returns the same shape the real one returned live on
2026-07-29: action_taken='search_web' with scraped page text as the message.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module      # noqa: E402


RAW = "- Gold PRICE Today: | Date | Open | Close | Danny Bakst By Danny Bakst"


@pytest.fixture
def ask(monkeypatch):
    calls = []

    def _orchestrate(q, session_id=None):
        calls.append(q)
        return {"action_taken": "search_web", "message": RAW}

    monkeypatch.setattr(app_module, "orchestrate", _orchestrate)
    monkeypatch.setattr(app_module, "detect_intent", lambda q: None)
    monkeypatch.setattr(app_module, "intent_agent", lambda q: {"intent": "chat"})
    monkeypatch.setattr(app_module, "is_concept_question", lambda q: None)
    monkeypatch.setattr(app_module, "needs_search", lambda q: False)
    monkeypatch.setattr(app_module, "record_activity", lambda **k: None)
    monkeypatch.setattr(app_module, "_extract_entities_from_message", lambda q: None)
    monkeypatch.setattr(app_module, "INTELLIGENCE_AVAILABLE", False)
    monkeypatch.setattr(app_module, "stream_llm",
                        lambda *a, **k: iter(['data: {"token": "SYNTHESIZED"}\n\n']))
    monkeypatch.setattr(app_module, "build_perception_context", lambda: "")
    monkeypatch.setattr(app_module, "build_screen_context", lambda: "")

    def _run(question):
        client = app_module.app.test_client()
        resp = client.post("/ask", json={"question": question,
                                         "session_id": "_info_test"})
        assert resp.status_code == 200
        return resp.get_data(as_text=True), calls

    return _run


def test_the_gold_question_is_not_answered_with_scraped_text(ask):
    body, _ = ask("What is the current price of gold per ounce?")

    assert "Danny Bakst" not in body
    assert "SYNTHESIZED" in body


def test_the_orchestrator_is_not_even_consulted_for_an_info_question(ask):
    """Cheaper and safer — its picker is what hijacked the browser tab."""
    _, calls = ask("who is al ronge")

    assert calls == []


def test_a_command_still_goes_to_the_orchestrator(ask):
    body, calls = ask("open chrome")

    assert calls == ["open chrome"]
    assert "Gold PRICE Today" in body      # the action's own message, as intended
