"""Turn a spoken sum into something safe_calculate can actually evaluate.

Observed live 2026-07-29: "what is 847 times 291" answered 246,297. The right
answer is 246,477.

intent_agent classified it as `calculate` correctly, but app.py handed
safe_calculate the whole sentence. It tried to evaluate the English, raised
"invalid syntax", returned success=False, and the request fell through to the
LLM — which did the multiplication in its head and got it wrong. Even
"what is 17*23" failed, on "name 'what' is not defined".

So the calculator was never actually reachable from chat. These tests assert
the extracted expression through safe_calculate, because the number at the end
is the thing that was wrong.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import math_phrase                       # noqa: E402
from action_engine import safe_calculate  # noqa: E402


def value(text):
    """Extract, evaluate, and return the number — the whole point of the chain."""
    expr = math_phrase.extract(text)
    assert expr is not None, f"nothing extracted from {text!r}"
    result = safe_calculate(expr)
    assert result.get("success"), f"{expr!r} -> {result}"
    return result["result"]


# ── the bug ──────────────────────────────────────────────────────────────────

def test_the_question_that_was_answered_wrong():
    assert value("what is 847 times 291") == 246477


def test_a_bare_operator_survives_the_lead_in():
    assert value("what is 17*23") == 391


# ── the rest of spoken arithmetic ────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("what is 2 plus 2",              4),
    ("what's 9 minus 4",              5),
    ("calculate 100 divided by 4",    25),
    ("compute 12 multiplied by 12",   144),
    ("how much is 30 percent of 200", 60),
    ("what is 2 to the power of 10",  1024),
])
def test_spoken_arithmetic(text, expected):
    assert value(text) == expected


def test_it_keeps_working_on_a_bare_expression():
    """/calculate already passes raw expressions — don't break that."""
    assert value("17*23") == 391


# ── it must not hijack ordinary questions ────────────────────────────────────

@pytest.mark.parametrize("text", [
    "what is the capital of France",
    "who is al ronge",
    "what is wheat leaf rust",
    "hello",
    "how many people live in India",
    "tell me about photosynthesis",
    "",
])
def test_questions_that_are_not_sums_extract_nothing(text):
    assert math_phrase.extract(text) is None


def test_a_year_alone_is_not_a_sum():
    """A bare number has no operator, so there is nothing to calculate."""
    assert math_phrase.extract("what happened in 1947") is None


def test_it_never_raises_on_junk():
    for junk in ("((((", "* * *", "\x00\x01", "٣٤٥"):
        math_phrase.extract(junk)      # must not raise
