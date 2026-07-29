# Search provenance and per-query source switch — design

**Date:** 2026-07-29
**Status:** approved, awaiting implementation plan
**Branch:** `phase13-strict-validation` (design written after `8617e78`)

## Problem

You cannot tell where an answer came from.

Which LLM answered is already visible — the provider pill in the top right
(`templates/index.html:392`), and every reply carries `{"_cost": {"provider":
"groq", ...}}`. That half is solved.

Which *search source* answered is invisible. `local_engine.local_smart_search`
returns one flat formatted string. The individual results do carry
`{"source": "duckduckgo"}`, but that is discarded during formatting — only the
`=== Web Search Results ===` and `=== Wikipedia ===` headers survive. Tavily's
path builds its own snippet string separately. Nothing downstream knows which
engine won, so an answer grounded in a paid Tavily lookup is indistinguishable
from one scraped off DuckDuckGo, or from one the model made up.

There is also no way to choose. Backend order is fixed at
`config.DEEP_SEARCH_ORDER`, an env var that applies only to Deep Research.

## What already exists

Worth stating, because a lot of this is built and must be reused rather than
reinvented:

| Piece | Where | Status |
|---|---|---|
| Numbered `[1]` citations + source list | `research_engine.synthesise` | Works, **Deep Research only** |
| Citation renumbering, handles grouped `[1, 2, 3]` | `research_engine._renumber_citations` | Works — reuse, do not rewrite |
| Deep Research UI toggle | `templates/index.html:122` (`deep-btn`) | Works |
| Backend order config | `config.DEEP_SEARCH_ORDER` | Deep Research only, not per-query |
| Backend functions | `local_engine.search_{tavily,searxng,duckduckgo,wikipedia_hits}` | Work; SearXNG returns nothing (not self-hosted) |
| Degraded-search logging | `search_trace.record` | Added `8617e78` |
| Question vs command | `info_question.is_info_question` | Added `8617e78` |
| No-sources disclosure to the model | `search_disclosure.apply` | Works |

Measured 2026-07-29 — Tavily 6/6 and 8/8 successful, ~0.95s median. Keyless
backends over 24 attempts each (8 query types × 3):

| Backend | Answered | Note |
|---|---|---|
| duckduckgo | **3/24 (12%)** | An earlier 6-attempt sample suggested 33%; the larger sample is the honest number. |
| wikipedia | 13/24 (54%) | Not flaky so much as narrow, and it rate-limits under rapid calls. |
| searxng | **0/24 (0%)** | Not self-hosted. Dead, not slow. |

Reliability overstates keyless usefulness, because a response is not an
answer. Wikipedia returned **"Electric current"** for *"current price of
bitcoin usd"*, and **"Jashodaben Modi"** (his wife) for *"who is Narendra
Modi"*. Live prices, news, weather and how-to questions returned nothing
usable at all. Keyless search is sound for encyclopedic facts and unfit for
anything time-sensitive — the badge must not imply otherwise.

## Design

### `search_router.py` (new)

The single place that decides which backend runs and reports what happened.
Replaces the inline Tavily-then-scraper ladder in `/ask`.

```python
route(query: str, mode: str = "auto") -> {
    "backend":        "tavily",       # who actually supplied the sources
    "keyless":        False,          # did this avoid the paid key?
    "requested":      "nokey",        # what the user asked for
    "fell_back_from": "duckduckgo",   # None when the request was honoured
    "sources":        [{"title", "url", "content"}, ...],
}
```

Chains per mode:

| Mode | Order | Rationale |
|---|---|---|
| `auto` | tavily → duckduckgo → wikipedia | Default; today's behaviour. Best answer available, cost not a concern. |
| `api` | tavily → wikipedia | **Skips the scraper.** Choosing "API key" means wanting trustworthy sourced data; falling onto a backend that answers 2 times in 6 is not what that asks for. |
| `nokey` | duckduckgo → wikipedia → tavily | Tavily last, only when both keyless backends find nothing. |

`fell_back_from` is the mode's *first-choice* backend whenever the winner is
not it — so `nokey` answered by Wikipedia reports `fell_back_from:
"duckduckgo"`, and `nokey` answered by Tavily also reports `"duckduckgo"`.
The badge derives "did this honour my request" from `keyless` and `requested`,
not from this field, which exists for the log and for debugging.

Every attempt is logged through the existing `search_trace.record`, so a
degraded lookup still leaves the line it leaves today.

### `citations.py` (new)

Two jobs, both pure:

1. Number the sources into the block handed to the model (`[1] title —
   content`), and instruct it to cite. The instruction extends the
   `SEARCH_USE_BLOCK` added in `8617e78`, which already tells the model to
   answer in its own words and name the date and source.
2. After the answer, drop sources the model never cited and renumber the rest
   contiguously — by calling `research_engine._renumber_citations`, not by
   reimplementing it.

### `app.py` — `/ask`

- Read `search_mode` from the request body (default `"auto"`).
- Replace the inline Tavily/scraper block with one `search_router.route(...)` call.
- Emit a new SSE event alongside `_cost`:

```json
{"_search": {"backend": "tavily", "keyless": false, "requested": "nokey",
             "fell_back_from": "duckduckgo",
             "sources": [{"title": "...", "url": "..."}]}}
```

Answers that ran no search emit `{"_search": {"backend": null}}` so the UI can
say so explicitly rather than showing nothing.

### `templates/index.html`

- Three buttons beside the model switcher, mirroring `switchModel`:
  `Search: [Auto] [API key] [No key]`. Selection persists across queries like
  the model choice does, and rides along in the `/ask` body.
- Under each answer: a Sources list, and a badge.

```
ULTRON-J
Air Ronge is a northern village in Saskatchewan,
Canada, 235 km north of Prince Albert [1].

Sources
[1] wikipedia.org/wiki/Air_Ronge

⚡ groq  ·  🔑 tavily (paid key)
```

Badge states:

| Situation | Badge |
|---|---|
| Paid key used | `🔑 tavily (paid key)` |
| Free API | `🆓 wikipedia (no key)` |
| Scraped | `🕸 duckduckgo (scraped)` |
| Request not honoured | `🕸 scraping failed → 🔑 tavily` |
| No search ran | `⚠ no web — from memory` |

### Voice (`voice_routes.py`)

Same router, same badge, same `_search` event. **No inline `[1]` markers in
spoken text** — they read badly aloud. The sources are still recorded and
still shown on screen.

## Decisions taken

- **Fall back, but label it.** A forced mode is a preference, not a hard rule.
  Ultron tries what you asked, then whatever works, and the badge names what it
  actually used. Rejected: refusing to answer, which trades a good answer for
  a point of principle.
- **Three modes, not four.** `Auto · API key · No key` matches how the ask was
  phrased ("webscraping or api key usage"). Naming all four engines is more
  control than the decision deserves each time.

## Known consequence

`No key` can still spend the Tavily key, because it falls back like every
other mode. The badge makes that visible (`🕸 scraping failed → 🔑 tavily`)
rather than silent. If a strict never-touch-the-key mode is wanted later, it
is a fourth chain in `search_router`, not a redesign.

## Out of scope

- Deep Research keeps its own chain, its own citations and its own toggle.
- `config.DEEP_SEARCH_ORDER` is unchanged.
- No new search backends. Self-hosting SearXNG (`setup_searxng.sh`, never run)
  remains the real fix for keyless search and is separate work.

## Testing

Following the pattern used in `8617e78` — a unit test file per pure module,
plus a wiring test that drives the real route:

- `search_router`: each mode's chain order; fallback recorded in
  `fell_back_from`; `keyless` correct per backend; every backend failing yields
  empty sources and no exception.
- `citations`: numbering; uncited sources dropped; grouped `[1, 2, 3]`
  renumbered (the bug `_renumber_citations` already fixes — assert it stays fixed).
- `/ask` wiring: `search_mode` reaches the router; `_search` event emitted with
  the right shape; an answer with no search reports `backend: null`.
- Regression gate: the 1516 existing tests stay green.
