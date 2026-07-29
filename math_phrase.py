"""Extract an evaluable arithmetic expression from a spoken question.

action_engine.safe_calculate takes a bare expression — "17*23". Chat hands it
whole sentences — "what is 17*23" — which it cannot parse, so it returned
success=False and app.py quietly fell through to the LLM. The LLM then did the
arithmetic from memory and got it wrong (847 times 291 came back as 246,297;
it is 246,477).

This is the missing step between the two: sentence in, expression out, None
when the sentence is not a sum at all. Deliberately conservative — a false
positive would hijack an ordinary question and answer it with a number.
"""
import re

# Longest first, so "multiplied by" is consumed before "multiplied", and
# "to the power of" before "of".
_WORD_OPS = [
    ("to the power of", "**"),
    ("multiplied by",   "*"),
    ("divided by",      "/"),
    ("percent of",      "*0.01*"),
    ("multiply by",     "*"),
    ("divide by",       "/"),
    ("multiply",        "*"),
    ("divide",          "/"),
    ("times",           "*"),
    ("plus",            "+"),
    ("minus",           "-"),
    ("add",             "+"),
    ("subtract",        "-"),
    ("squared",         "**2"),
    ("cubed",           "**3"),
]

# Conversational lead-ins that are never part of the sum.
_LEAD_INS = [
    "what is", "what's", "whats", "how much is", "how much",
    "calculate", "compute", "work out", "tell me", "please", "the answer to",
]

_ALLOWED = re.compile(r"[\d\s\+\-\*\/\(\)\.\%]")
_HAS_DIGIT = re.compile(r"\d")
_HAS_OP = re.compile(r"[\+\-\*\/]")


def extract(text) -> str | None:
    """Return an expression safe_calculate can evaluate, or None.

    None means "this is not arithmetic" — the caller should carry on to the
    LLM rather than answering with a number.
    """
    try:
        s = str(text or "").lower().strip()
        if not s:
            return None

        for phrase in _LEAD_INS:
            if s.startswith(phrase):
                s = s[len(phrase):].strip()

        for word, symbol in _WORD_OPS:
            s = re.sub(rf"\b{re.escape(word)}\b", symbol, s)

        # "5 x 3" reads as multiplication only between two numbers.
        s = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", s)

        # Drop thousands separators before the comma is stripped as junk,
        # so "1,000 + 5" does not become "1000 5".
        s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)

        # Anything that is not math is a word, and a word means this was not a
        # sum. Bail rather than silently computing part of a sentence.
        if re.search(r"[a-z]", s):
            return None

        expr = "".join(_ALLOWED.findall(s)).strip()

        # Needs both a number and something to do with it. This is what keeps
        # "what happened in 1947" from being treated as a calculation.
        if not (_HAS_DIGIT.search(expr) and _HAS_OP.search(expr)):
            return None
        return expr
    except Exception:
        return None
