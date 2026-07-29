"""Assertions the live eval harness makes about an answer.

Pure functions, no network — so they are unit-tested in
tests/test_eval_checks.py against the real answers Ultron gave on 2026-07-29,
both the broken ones and their fixed replacements.
"""
import re

# The header the search context is wrapped in. If this reaches the user, raw
# context leaked into the reply instead of being read and answered from.
_CONTEXT_MARKERS = (
    "=== Web Search Results ===",
    "=== Wikipedia ===",
    "[WEB SEARCH RETURNED NO SOURCES]",
)

# Scraped pages are full of these; a spoken answer never is.
_TABLE_ROW = re.compile(r"\|[^|\n]*\|[^|\n]*\|")
_MD_HEADING = re.compile(r"^#{1,6}\s", re.MULTILINE)
_SNIPPET_LEAD = re.compile(r"^\s*[-•]\s*[^\n:]{8,90}:\s", re.MULTILINE)

# Phrases that count as owning up to a failed lookup.
# A number carrying a unit or scale word. Deliberately excludes bare integers,
# so a year mentioned in background prose does not read as a retrieved figure.
_QUANTITY = re.compile(
    r"\d[\d,]*\s*(million|billion|trillion|thousand|crore|lakh|"
    r"tonnes?|tons?|kg|kilograms?|quintals?|hectares?|acres?|"
    r"degrees?|percent|per cent)\b"
)

_ADMISSIONS = (
    "could not reach", "couldn't reach", "no sources", "not able to retrieve",
    "unable to retrieve", "don't have access", "do not have access",
    "no live data", "from memory", "may be out of date", "may be outdated",
    "i don't have information", "i do not have information",
    "could not find", "couldn't find",
)


def _text(value) -> str:
    try:
        return str(value or "")
    except Exception:
        return ""


def looks_like_raw_dump(answer) -> str | None:
    """Return why `answer` looks like pasted page text, or None if it reads fine.

    Empty answers return None — that is a different failure and the harness
    reports it separately rather than mislabelling it.
    """
    text = _text(answer)
    if not text.strip():
        return None

    for marker in _CONTEXT_MARKERS:
        if marker in text:
            return f"search context leaked into the reply ({marker!r})"

    if _TABLE_ROW.search(text):
        return "contains a markdown table row — scraped page furniture"

    if _SNIPPET_LEAD.search(text):
        return "starts with a '- <title>: ' search snippet rather than an answer"

    if _MD_HEADING.search(text):
        return "contains a markdown heading — chat answers never use them"

    # A byline or nav item repeated verbatim. Real prose does not do this.
    lines = [ln.strip() for ln in text.splitlines() if 3 < len(ln.strip()) < 60]
    for line in set(lines):
        if lines.count(line) >= 3:
            return f"line repeated {lines.count(line)}x — page furniture ({line!r})"

    return None


def has_number(answer, expected) -> bool:
    """True when `expected` appears as a number in `answer`.

    Tolerates thousands separators and a leading '='; rejects near misses,
    which is the whole point — 246,297 must not pass for 246,477.
    """
    text = _text(answer)
    try:
        target = float(expected)
    except (TypeError, ValueError):
        return False
    for raw in re.findall(r"-?\d[\d,]*\.?\d*", text):
        try:
            if float(raw.replace(",", "")) == target:
                return True
        except ValueError:
            continue
    return False


def answers_or_admits(answer) -> bool:
    """True when a live-data question got a figure, or an honest 'I couldn't'.

    The failure this catches is the quiet third option: a confident-sounding
    reply built from training data, with no figure and no admission that
    nothing was retrieved.
    """
    text = _text(answer)
    if not text.strip():
        return False
    low = text.lower()
    if any(phrase in low for phrase in _ADMISSIONS):
        return True
    # A currency figure, a decimal or a percentage reads as a retrieved value.
    if re.search(r"[$₹€£]\s?\d|\d[\d,]*\.\d|\d+\s?%", text):
        return True
    # So does a quantity with a unit — "5 million tonnes" is as concrete as
    # "$63,730". A bare year is not, which is what keeps "created in 2009"
    # from passing as a retrieved fact.
    return bool(_QUANTITY.search(low))
