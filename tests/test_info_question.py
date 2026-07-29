"""Info-shaped questions must not be answered by the action orchestrator.

Observed live 2026-07-29: "What is the current price of gold per ounce?"
returned scraped page text verbatim, table pipes and author byline included.

task_orchestrator classified it action_taken='search_web', passthrough=None,
so app.py:748 returned the action's message as the answer — the LLM was never
called. smart_browser_agent.py:204 formats those snippets as "- {title}:
{content}", which is exactly what landed on screen.

voice_routes.py:608 already guards against this ("its LLM picker can map them
to search_web ... Info questions go straight to the LLM+Tavily path below").
app.py never got the same guard. This module is that check, shared, so the two
routes cannot drift apart.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import info_question  # noqa: E402


@pytest.mark.parametrize("text", [
    "What is the current price of gold per ounce?",
    "How much does one Bitcoin cost right now?",
    "how much is a tonne of wheat",
    "who is al ronge",
    "what's the capital of France",
    "when did the green revolution start",
    "where is Hyderabad",
    "why does wheat rust spread",
    "how do I treat leaf rust",
    "tell me about photosynthesis",
    "explain crop rotation",
    "do you know what septoria is",
])
def test_questions_that_want_an_answer_not_an_action(text):
    assert info_question.is_info_question(text) is True


@pytest.mark.parametrize("text", [
    "open chrome",
    "take a screenshot",
    "volume up",
    "play music on youtube",
    "create a file called notes.txt",
    "lock the screen",
    "search youtube for wheat farming",
    "pause the video",
])
def test_commands_still_reach_the_orchestrator(text):
    assert info_question.is_info_question(text) is False


def test_it_is_case_and_space_insensitive():
    assert info_question.is_info_question("   WHAT IS wheat rust?  ") is True


def test_the_bare_phrase_counts_as_a_question():
    assert info_question.is_info_question("tell me") is True


@pytest.mark.parametrize("junk", ["", "   ", None, 12345])
def test_it_never_raises_on_junk(junk):
    assert info_question.is_info_question(junk) is False


def test_a_lead_in_must_be_a_prefix_not_a_substring():
    """"...what is..." mid-sentence is a command, not a question."""
    assert info_question.is_info_question("open the file and tell me what is inside") is False
