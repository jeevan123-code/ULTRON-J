"""When a web search returns nothing, Ultron must say so.

app.py used to short-circuit the whole reply with "I couldn't reach any web
sources", which refused too much — a casual "today" would trigger a search and
then a refusal. That was replaced by silently continuing with no sources, which
is worse in a different way: the model answers from memory and the user cannot
tell that nothing was actually looked up. Every search engine is currently
returning 202/CAPTCHA to us, so this is the common case, not the rare one.

The fix is neither refusing nor pretending: hand the model an explicit notice
that it has no live data and must disclose that.
"""
import search_disclosure as sd


def test_real_search_context_passes_through_untouched():
    ctx = "• Wikipedia: Argentina won on penalties"
    assert sd.apply(ctx, searched=True) == ctx


def test_no_search_attempted_stays_empty():
    # The question never needed a search — nothing to disclose.
    assert sd.apply("", searched=False) == ""


def test_failed_search_injects_a_disclosure_notice():
    out = sd.apply("", searched=True)
    assert out != ""
    assert "NO" in out.upper()
    low = out.lower()
    assert "outdated" in low or "could not" in low or "couldn't" in low


def test_notice_tells_the_model_to_answer_anyway():
    # We are not going back to refusing; it must still answer.
    low = sd.apply("", searched=True).lower()
    assert "answer" in low
    assert "refuse" not in low


def test_notice_forbids_claiming_the_answer_was_researched():
    low = sd.apply("", searched=True).lower()
    assert "current" in low or "researched" in low or "live" in low


def test_whitespace_only_context_counts_as_failure():
    assert sd.apply("   \n  ", searched=True) == sd.apply("", searched=True)


def test_notice_is_stable():
    assert sd.apply("", searched=True) == sd.apply("", searched=True)


def test_partial_context_is_not_overwritten():
    ctx = "• one weak source"
    assert sd.apply(ctx, searched=True) == ctx
