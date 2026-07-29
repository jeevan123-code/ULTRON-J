"""Checks for the live eval harness, built from the failures of 2026-07-29.

Every fixture marked BAD_ is a real answer Ultron gave that day, copied
verbatim. Every GOOD_ is a real answer it gave after the fixes. The point of
the harness is that the 1516-test suite was green the entire time the BAD_
answers were being served — those bugs lived in the wiring between components,
where only a live request finds them.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals import checks  # noqa: E402


# ── real answers from before the fix ─────────────────────────────────────────

BAD_GOLD_TABLE = (
    "- Gold PRICE Today | Live Price of Gold per Ounce: | Date | Open | Close "
    "| Daily High | Daily Low |\n\nPrice change over selected period:  0% 0\n\n"
    "## Unit conversion for Gold Price Today\n\n| Conversion | Gold Price(Spot) "
    "| Price |\n| 1 Troy Ounce = 31,10 Gram | Gold Price Per 1 Gram | 130.99 USD"
)

BAD_GOLD_BYLINE = (
    "- Current price of gold: July 22, 2026: # 3\n\nCurrent price of oil as of "
    "July 28, 2026\n\nPersonal Financegold prices\n\n# Current price of gold as "
    "of July 22, 2026\n\nDanny Bakst\n\nBy \n\nDanny Bakst\n\nDanny Bakst\n\n"
    "Director of Affiliate Marketing"
)

BAD_BITCOIN = (
    "- Bitcoin price today, BTC to USD live price, marketcap ...: ### Bitcoin "
    "Price Live Data\n\nThe live Bitcoin price today is $63,553.51 USD with a "
    "24-hour trading volume of $27,514,068,563 USD.We update our BTC to USD "
    "price in real-time."
)

# ── real answers from after the fix ──────────────────────────────────────────

GOOD_BITCOIN = ("As of July 28, 2026, CoinMarketCap lists the current price of "
                "Bitcoin at $63,730 USD.")
GOOD_PLACE = ("Air Ronge is a northern village in Saskatchewan, Canada, located "
              "235 km north of Prince Albert.")
GOOD_MATH = "= 246477"
GOOD_REFUSAL = ("I could not reach any web sources, so this is from memory and "
                "may be out of date.")


# ── the dump detector ────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [BAD_GOLD_TABLE, BAD_GOLD_BYLINE, BAD_BITCOIN])
def test_it_catches_the_answers_that_were_really_served(bad):
    assert checks.looks_like_raw_dump(bad) is not None


@pytest.mark.parametrize("good", [GOOD_BITCOIN, GOOD_PLACE, GOOD_MATH, GOOD_REFUSAL])
def test_it_clears_the_answers_that_are_actually_fine(good):
    assert checks.looks_like_raw_dump(good) is None


def test_it_says_why_so_a_failure_is_actionable():
    assert "table" in checks.looks_like_raw_dump(BAD_GOLD_TABLE).lower()


def test_a_repeated_byline_is_caught_even_without_a_table():
    """The gold answer repeated 'Danny Bakst' three times — page furniture."""
    assert checks.looks_like_raw_dump(BAD_GOLD_BYLINE) is not None


def test_the_search_context_header_must_never_reach_the_user():
    assert checks.looks_like_raw_dump("=== Web Search Results ===\n1. Wheat") is not None


def test_an_empty_answer_is_not_a_dump():
    """Empty is a different failure — the harness reports it separately."""
    assert checks.looks_like_raw_dump("") is None


# ── numeric answers ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("= 246477",                        246477),
    ("The answer is 246,477.",          246477),
    ("246477",                          246477),
    ("It comes to 246,477 exactly.",    246477),
])
def test_it_finds_the_number_however_it_is_written(text, expected):
    assert checks.has_number(text, expected) is True


def test_it_rejects_the_wrong_number():
    """This is the check that would have caught 246,297."""
    assert checks.has_number("The result is 246,297.", 246477) is False


def test_a_near_miss_is_still_a_miss():
    assert checks.has_number("246478", 246477) is False


# ── live-data questions: answer it, or say you couldn't ──────────────────────

def test_a_real_figure_counts_as_answered():
    assert checks.answers_or_admits(GOOD_BITCOIN) is True


def test_an_honest_failure_counts_too():
    assert checks.answers_or_admits(GOOD_REFUSAL) is True


def test_a_concrete_quantity_counts_even_without_a_currency_symbol():
    """Flagged the wheat-news answer as ungrounded when it was not.

    Tavily returned 5 sources dated that day and the reply used them; the
    check simply demanded a currency figure, which a news answer need not
    have. An eval that cries wolf gets ignored, so this is the check being
    wrong rather than Ultron.
    """
    assert checks.answers_or_admits(
        "The Indian government has lifted a four-year ban on wheat exports, "
        "allowing 5 million tonnes to be exported."
    ) is True


def test_a_bare_year_is_not_a_retrieved_figure():
    """Guards the fix above from becoming 'any digit passes'."""
    assert checks.answers_or_admits(
        "Bitcoin is a decentralised digital currency created in 2009."
    ) is False


def test_silently_having_neither_is_the_failure():
    """The refusal that pretended it had no search: no figure, no admission."""
    assert checks.answers_or_admits(
        "Bitcoin is a decentralised digital currency created in 2009."
    ) is False


def test_yaml_booleans_fail_the_case_instead_of_crashing_the_run():
    """`contains_any: [yes]` parses as [True] — YAML's oldest trap.

    It killed two cases with "'bool' object has no attribute 'lower'" on the
    harness's first run, mid-sweep. Quoting in cases.yaml is the real fix. The
    evaluator's job is to make forgetting cost a readable failure on one case
    rather than an exception that looks like Ultron broke.
    """
    from evals.run_evals import evaluate

    fails = evaluate({"contains_any": [True]}, "Yes, wheat is a plant.", "")

    assert fails, "an unquoted yes cannot silently pass"
    assert "true" in " ".join(fails).lower()   # names the term it actually looked for
    assert not any("AttributeError" in f for f in fails)


def test_no_check_type_crashes_on_a_boolean():
    from evals.run_evals import evaluate

    for expect in ({"contains": [False]}, {"not_contains": [True]},
                   {"contains_any": [False]}):
        evaluate(expect, "No, it is not.", "")     # must not raise


def test_junk_never_raises():
    for junk in (None, 12345, "", "   ", "\x00"):
        checks.looks_like_raw_dump(junk)
        checks.answers_or_admits(junk)
        checks.has_number(junk, 1)
