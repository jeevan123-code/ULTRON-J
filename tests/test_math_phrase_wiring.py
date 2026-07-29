"""Chat arithmetic must reach the calculator, not the language model.

math_phrase is unit-tested in test_math_phrase.py; this covers the GLUE.

intent_agent already classifies "what is 847 times 291" as `calculate` — the
break was that app.py passed the raw sentence to safe_calculate, which could
not parse it, so the request fell through to the LLM and came back 246,297
instead of 246,477.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module      # noqa: E402


@pytest.fixture
def ask(monkeypatch):
    """POST /ask with the pre-intent intercepts stubbed out.

    intent_agent is deliberately NOT stubbed — its routing is already correct
    and this test should fail if that ever regresses.
    """
    monkeypatch.setattr(app_module, "orchestrate",
                        lambda q, session_id=None: {"passthrough": True})
    monkeypatch.setattr(app_module, "detect_intent", lambda q: None)

    # If the calculator is missed, the request falls through to the LLM. Stub
    # it so that path is fast and obviously wrong rather than slow and random.
    monkeypatch.setattr(app_module, "INTELLIGENCE_AVAILABLE", False)
    monkeypatch.setattr(app_module, "stream_llm",
                        lambda *a, **k: iter(['data: {"done": true}\n\n']))

    def _run(question):
        client = app_module.app.test_client()
        resp = client.post("/ask", json={"question": question,
                                         "session_id": "_math_test"})
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    return _run


def test_the_question_that_was_answered_wrong(ask):
    assert "246477" in ask("what is 847 times 291")


def test_it_is_the_calculator_answering_not_the_model(ask):
    assert "calculate" in ask("what is 847 times 291")


def test_a_bare_operator_still_works(ask):
    assert "391" in ask("what is 17*23")


def test_spoken_division(ask):
    assert "25" in ask("calculate 100 divided by 4")


def test_an_ordinary_question_is_not_answered_with_a_number(ask):
    """The fall-through must survive — this one belongs to the LLM."""
    body = ask("who is al ronge")

    assert "246477" not in body
    assert "provider=calculate" not in body
