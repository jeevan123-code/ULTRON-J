"""Tell the model when a web search came back empty, so it can tell the user.

There were two previous behaviours, both wrong:

  1. Refuse the whole reply ("I couldn't reach any web sources"). Too blunt —
     a casual "what's happening today" tripped the search heuristic and then
     got refused.
  2. Continue silently with no sources. The model then answers from memory and
     the user has no way to know nothing was actually retrieved.

(2) is the current behaviour and it is the source of the "it gives me false
info" complaint: every search engine is presently answering our requests with
202 / CAPTCHA, so the no-sources path is the COMMON path, not a rare one.

This module is the middle road — still answer, but disclose. One place, so the
text and the rule stay identical for the text route and the voice route.
"""

NO_SOURCES_NOTICE = (
    "[WEB SEARCH RETURNED NO SOURCES]\n"
    "Live retrieval failed for this question — you have no web data at all.\n"
    "Answer from your own knowledge, but you MUST open by telling the user "
    "plainly that you could not reach any sources and that what follows may be "
    "outdated or incomplete. Do not present it as current, live, or researched, "
    "and do not invent citations, URLs or source names."
)


def apply(search_context: str, searched: bool) -> str:
    """Return the context to hand the model.

    `searched` is whether a web lookup was actually attempted. If it was and
    produced nothing usable, substitute the disclosure notice; otherwise the
    caller's context passes through untouched.
    """
    if not searched:
        return search_context or ""
    if (search_context or "").strip():
        return search_context
    return NO_SOURCES_NOTICE
