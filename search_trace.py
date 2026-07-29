"""Leave a trace when a web-search backend degrades.

The companion to search_disclosure. That module tells the MODEL a search came
back empty so it can warn the user; this one tells the OPERATOR why it came
back empty, in the server log.

It exists because the /ask search block did this:

    except Exception as _te:
        tavily = {"sources": [], "error": str(_te)[:120]}

and nothing ever read that "error" key. Neither did anything report the more
common failure — Tavily returning zero sources without raising at all. So when
Ultron silently fell back to the DuckDuckGo scraper, the reason was already
gone by the time anyone went looking.

One line per degraded attempt, one stable prefix to grep for. Diagnostics must
never be the reason a reply fails, so record() swallows everything.
"""

PREFIX = "[search]"

_MAX_QUERY = 80    # enough to recognise the question, short enough to stay inline
_MAX_ERROR = 120   # matches the truncation app.py already used


def _safe(value, limit: int) -> str:
    """str() that cannot raise, flattened to a single line and truncated."""
    try:
        text = str(value)
    except Exception:
        text = "<unprintable>"
    text = " ".join(text.split())
    return text[:limit]


def record(backend: str, query, *, sources: int = 0,
           error=None, skipped: str = "") -> str:
    """Print and return a one-line trace for a web-search attempt.

    Returns "" when the attempt succeeded and there is nothing to report, so
    a healthy search stays silent in the log.
    """
    try:
        if error is not None:
            reason = f"error={_safe(error, _MAX_ERROR)}"
        elif skipped:
            reason = f"skipped={_safe(skipped, _MAX_ERROR)}"
        elif not sources:
            reason = "0 sources"
        else:
            return ""

        line = (f"{PREFIX} {_safe(backend, 40)} {reason} "
                f"query={_safe(query, _MAX_QUERY)!r}")
        print(line)
        return line
    except Exception:
        # A diagnostic that breaks the caller is worse than no diagnostic.
        return ""
