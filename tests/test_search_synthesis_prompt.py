"""Search results must be given to the model as raw material, not as the answer.

Observed live 2026-07-29 — asked for the gold price, Ultron replied with the
scraped page verbatim, author byline included:

    - Current price of gold: July 22, 2026: # 3
    Personal Financegold prices
    Danny Bakst  By  Danny Bakst  Danny Bakst
    Director of Affiliate Marketing

Bitcoin behaved the same way. Both prompt builders file search results under
"LIVE REALITY: ... Use this if relevant. Never contradict it." — an
instruction to TRUST the block, with nothing telling the model to answer from
it in its own words. The fast model duly copied it out.

A reworded Bitcoin question failed the opposite way ("I don't have direct
access to real-time cryptocurrency prices") with needs_search=True, so the
same context is sometimes echoed and sometimes ignored. Neither is synthesis.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import intelligence_core as ic  # noqa: E402


BUILDERS = pytest.mark.parametrize("build", [
    ic._build_simple_system_prompt,
    ic._build_medium_system_prompt,
])

SEARCHY = ic.SEARCH_RESULTS_HEADER + "\nBitcoin is down 2.81% in the last 24 hours."
PLAIN = "Local time is 21:04. Battery 74%."


@BUILDERS
def test_a_prompt_carrying_search_results_demands_synthesis(build):
    prompt = build(SEARCHY, "")

    assert ic.SEARCH_USE_BLOCK in prompt


@BUILDERS
def test_a_prompt_without_search_results_is_not_bloated_by_it(build):
    prompt = build(PLAIN, "")

    assert ic.SEARCH_USE_BLOCK not in prompt


@BUILDERS
def test_the_search_block_still_reaches_the_model(build):
    """The fix must not cost us the results themselves."""
    prompt = build(SEARCHY, "")

    assert "Bitcoin is down 2.81%" in prompt


# ── what the instruction has to actually say ─────────────────────────────────

def test_it_forbids_pasting_the_block():
    text = ic.SEARCH_USE_BLOCK.lower()

    assert "own words" in text
    assert "paste" in text


def test_it_names_the_page_furniture_that_leaked_into_the_answer():
    text = ic.SEARCH_USE_BLOCK.lower()

    assert "byline" in text or "author" in text
    assert "navigation" in text


def test_it_requires_admitting_a_missing_fact_rather_than_dumping():
    text = ic.SEARCH_USE_BLOCK.lower()

    assert "say so" in text
