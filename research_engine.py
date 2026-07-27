"""
research_engine.py — Claude-like research pipeline for Ultron-J.

Goes well beyond the existing local_smart_search / ResearchAgent combos:

  1. QUERY DECOMPOSITION    break the question into 2-4 focused sub-queries
  2. PRIOR-WORK CHECK       vector_store.find_prior_research — skip if done
  3. PARALLEL SEARCH        each sub-query hits SearXNG/DDG in parallel
  4. DEEP FETCH             read top 3 pages per sub-query for full content
  5. SOURCE DIVERSITY       drop duplicate domains, prefer primary sources
  6. PER-SUB-QUERY EXTRACT  LLM pulls only the relevant quote(s) from each page
  7. CROSS-REFERENCE        LLM checks for contradictions across sources
  8. SYNTHESISE             final answer with numbered citations [1], [2]
  9. CACHE IN VECTOR STORE  so next time, we recall instead of re-searching

Public API:
    research(question, depth="standard") -> {
        "answer":      "markdown with [1] [2] citations",
        "sources":     [{"n": 1, "url": ..., "title": ...}, ...],
        "sub_queries": [...],
        "contradictions": [...],
        "cached":      False,
        "ms":          1234,
    }

depth options:
    "quick"    — 1 query, 2 pages each, ~10s
    "standard" — 2-3 queries, 3 pages each, ~30s
    "deep"     — 3-4 queries, 4 pages each, cross-reference pass, ~60s
"""

import json
import re
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

try:
    from local_engine import (
        search_searxng, search_duckduckgo, search_wikipedia, search_tavily,
        search_wikipedia_hits,
    )
    _SEARCH_AVAILABLE = True
except ImportError:
    _SEARCH_AVAILABLE = False
    def search_searxng(q, max_results=5): return []
    def search_duckduckgo(q, max_results=5): return []
    def search_wikipedia(q): return ""
    def search_tavily(q, max_results=5): return []
    def search_wikipedia_hits(q, max_results=5): return []

# Configurable backend order (set DEEP_SEARCH_ORDER to e.g.
# "searxng,duckduckgo,tavily" once SearXNG is self-hosted, to drop the Tavily
# dependency). Unknown names are ignored.
try:
    from config import DEEP_SEARCH_ORDER as _DEEP_SEARCH_ORDER
except ImportError:
    # Wikipedia is last but always present: as of 2026-07-26 it is the only
    # keyless backend that still answers (the rest return 202 or a CAPTCHA), so
    # it is what stands between a failed search and a silent memory-answer.
    _DEEP_SEARCH_ORDER = "tavily,searxng,duckduckgo,wikipedia"
_BACKENDS = {
    "tavily":     search_tavily,
    "searxng":    search_searxng,
    "duckduckgo": search_duckduckgo,
    "ddg":        search_duckduckgo,
    "wikipedia":  search_wikipedia_hits,
    "wiki":       search_wikipedia_hits,
}
def _backend_chain():
    chain = []
    for name in _DEEP_SEARCH_ORDER.split(","):
        fn = _BACKENDS.get(name.strip().lower())
        if fn and fn not in chain:
            chain.append(fn)
    # Wikipedia is appended unconditionally as the last resort — a custom
    # DEEP_SEARCH_ORDER must not be able to leave zero working backends.
    if search_wikipedia_hits not in chain:
        chain.append(search_wikipedia_hits)
    return chain

try:
    from autonomous_browser import browse as _ab_browse
    _BROWSER_AVAILABLE = True
except ImportError:
    _BROWSER_AVAILABLE = False
    def _ab_browse(url, js=False): return {"success": False, "text": ""}

try:
    import model_selector as ms
except ImportError:
    ms = None

try:
    from llm_engine import call_llm_batch
except ImportError:
    def call_llm_batch(p, **kw): return ""

# Deep-research cascade — the per-page extraction step runs on a cheap, fast
# model (Groq 8B) so reading 4-16 scraped pages stays inexpensive; the final
# synthesis stays on the smart model. If Groq isn't configured, callers fall
# back to the normal model_selector / call_llm_batch path (smart model).
try:
    from config import GROQ_EXTRACT_MODEL, GROQ_KEYS as _GROQ_KEYS
except ImportError:
    GROQ_EXTRACT_MODEL = None
    _GROQ_KEYS = []


import threading as _threading
# The deep engine extracts from several pages concurrently. On a free LLM tier,
# firing those calls all at once trips the per-minute rate limit (429) and the
# extracts come back empty. Serialize them with a small gap so they queue
# instead of bursting — a few seconds slower, but reliable.
_extract_lock      = _threading.Lock()
_extract_last_call = [0.0]
_EXTRACT_MIN_GAP   = 0.4  # seconds between cheap-model extraction calls


def _extract_llm(prompt: str, system: str) -> str:
    """Run a cheap-model extraction call (Groq 8B) for the cascade, throttled to
    avoid the free-tier burst rate limit. Returns '' if unavailable so the
    caller can fall back to the smart model."""
    if not (_GROQ_KEYS and GROQ_EXTRACT_MODEL):
        return ""
    with _extract_lock:
        gap = time.time() - _extract_last_call[0]
        if gap < _EXTRACT_MIN_GAP:
            time.sleep(_EXTRACT_MIN_GAP - gap)
        try:
            out = call_llm_batch(prompt, system=system,
                                 provider="groq", model=GROQ_EXTRACT_MODEL) or ""
        except Exception:
            out = ""
        _extract_last_call[0] = time.time()
        return out

try:
    import vector_store
    _VSTORE_AVAILABLE = True
except ImportError:
    _VSTORE_AVAILABLE = False


# =============================================================================
# CONFIG
# =============================================================================

DEPTH_CONFIG = {
    # cross_ref is the fact-checker: it reads every extract side by side and
    # flags where sources actually disagree. It was written, tested, and then
    # only enabled on "deep" — which is not the depth normal questions use, so
    # in practice nothing was ever cross-checked. On for standard now; quick
    # stays off because quick is the "just answer fast" setting.
    "quick":    {"n_subqueries": 1, "pages_per_q": 2, "max_chars_per_page": 2500, "cross_ref": False},
    "standard": {"n_subqueries": 3, "pages_per_q": 3, "max_chars_per_page": 3500, "cross_ref": True},
    "deep":     {"n_subqueries": 4, "pages_per_q": 4, "max_chars_per_page": 5000, "cross_ref": True},
}

# Domains dropped outright (content farms / aggregator-only)
_LOW_QUALITY_DOMAINS = {
    "pinterest.com", "quora.com", "answers.yahoo.com",
    "reference.com", "wikihow.com",
}

# ── source authority ─────────────────────────────────────────────────────────
# Ranking used to be "whatever the search engine returned, minus duplicates",
# which is how a Facebook post outranked Wikipedia on a factual question. These
# tiers reorder within that result set; they never invent or remove sources
# except for the hard-drop list above.
AUTHORITY_HIGH    = 3   # reference works, official bodies, wire services
AUTHORITY_NEUTRAL = 2   # anything unrecognised — the default
AUTHORITY_SOCIAL  = 1   # user-generated: demoted, NOT banned (reddit is
                        # genuinely the best source for some questions)

_HIGH_DOMAINS = {
    "wikipedia.org", "britannica.com", "nature.com", "science.org",
    "sciencedirect.com", "arxiv.org", "pubmed.ncbi.nlm.nih.gov", "who.int",
    "nasa.gov", "noaa.gov", "reuters.com", "apnews.com", "bbc.com",
    "bbc.co.uk", "npr.org", "pbs.org", "nytimes.com", "theguardian.com",
    "ft.com", "economist.com", "nih.gov", "cdc.gov", "esa.int",
}
_HIGH_SUFFIXES = (".gov", ".edu", ".ac.uk", ".gov.uk", ".int", ".mil")

_SOCIAL_DOMAINS = {
    "facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com",
    "reddit.com", "medium.com", "blogspot.com", "wordpress.com", "tumblr.com",
    "threads.net", "linkedin.com", "substack.com", "quora.com",
    # Video platforms: a scraped watch page is player UI, not content.
    "youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "twitch.tv",
}

# A page has to actually say something before it earns a citation. The live
# failure this fixes: a JS-rendered Facebook post returned 116 characters and
# still became source [1].
MIN_PAGE_CHARS = 400


def _authority(url: str) -> int:
    """Score a URL's source tier. Subdomain- and case-insensitive."""
    dom = _domain(url)
    if not dom:
        return AUTHORITY_NEUTRAL
    for known in _HIGH_DOMAINS:
        if dom == known or dom.endswith("." + known):
            return AUTHORITY_HIGH
    if dom.endswith(_HIGH_SUFFIXES):
        return AUTHORITY_HIGH
    for known in _SOCIAL_DOMAINS:
        if dom == known or dom.endswith("." + known):
            return AUTHORITY_SOCIAL
    return AUTHORITY_NEUTRAL


def _is_citable(text) -> bool:
    """Did this page give us enough substance to cite it?"""
    return bool(text) and len(str(text).strip()) >= MIN_PAGE_CHARS


# =============================================================================
# STEP 1: QUERY DECOMPOSITION
# =============================================================================

_DECOMPOSE_SYSTEM = """You take a user question and output 1-4 focused sub-queries that together
will answer it fully. Output ONLY JSON in this format:
{ "sub_queries": ["...", "..."] }

Rules:
- Each sub-query should be a natural-language web search query (5-12 words).
- Cover the DIFFERENT facets of the question: what/why/how/when/current state.
- Do NOT paraphrase the same question 4 times.
- For simple factual lookups, one sub-query is enough — don't pad.
- For comparisons ("X vs Y") produce at least one sub-query per entity.
- If the question already IS a concrete search query, return it alone.
"""


def decompose(question: str, max_subqueries: int = 3) -> List[str]:
    prompt = f'Decompose into up to {max_subqueries} sub-queries:\n\n"{question.strip()}"'
    if ms:
        parsed = ms.call_json("decompose", prompt, system=_DECOMPOSE_SYSTEM)
    else:
        raw = call_llm_batch(prompt, system=_DECOMPOSE_SYSTEM, provider="gemini")
        parsed = _parse_json_loose(raw)

    if isinstance(parsed, dict) and isinstance(parsed.get("sub_queries"), list):
        subs = [str(s).strip() for s in parsed["sub_queries"] if str(s).strip()]
        if subs:
            return subs[:max_subqueries]
    # Fallback: use the original question
    return [question.strip()]


def _parse_json_loose(raw: str) -> Optional[Dict]:
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"(\{.*\})", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
    return None


# =============================================================================
# STEP 2: SEARCH (per sub-query)
# =============================================================================

def search_one(query: str, n_results: int = 5) -> List[Dict]:
    """Run one sub-query through a resilient backend chain, dedupe by URL.

    Order = most-reliable first: Tavily (if a key is set — built for
    concurrency, returns extracted content) → SearXNG (keyless, if you've
    self-hosted one) → DuckDuckGo (keyless, throttled fallback). Any single
    working backend yields sources, so there's no hard dependency on Tavily —
    drop the key and it falls through to SearXNG/DDG automatically.
    """
    combined: Dict[str, Dict] = {}  # keyed by URL

    for backend in _backend_chain():
        if len(combined) >= n_results:
            break
        try:
            hits = backend(query, max_results=n_results) or []
        except Exception:
            hits = []
        for hit in hits:
            url = (hit.get("url") or "").strip()
            if url and url not in combined:
                combined[url] = {
                    "url":     url,
                    "title":   hit.get("title", ""),
                    "snippet": hit.get("snippet", ""),
                    "origin":  hit.get("source", "?"),
                }

    return list(combined.values())


def diversify_sources(all_hits: List[Dict], max_total: int = 10) -> List[Dict]:
    """Drop duplicate domains, order by source authority. Returns up to max_total.

    The sort is stable, so within a tier the search engine's own ranking is
    preserved — this reorders tiers, it does not re-rank results.
    """
    all_hits = sorted(all_hits, key=lambda h: -_authority(h.get("url", "")))
    seen_domains: Dict[str, int] = {}
    out: List[Dict] = []
    # First pass: one per domain
    for hit in all_hits:
        dom = _domain(hit["url"])
        if dom in _LOW_QUALITY_DOMAINS:
            continue
        if seen_domains.get(dom, 0) >= 1:
            continue
        seen_domains[dom] = seen_domains.get(dom, 0) + 1
        out.append(hit)
        if len(out) >= max_total:
            return out
    # Second pass: allow a second hit from a domain if we're still short
    for hit in all_hits:
        if hit in out:
            continue
        dom = _domain(hit["url"])
        if dom in _LOW_QUALITY_DOMAINS:
            continue
        if seen_domains.get(dom, 0) >= 2:
            continue
        seen_domains[dom] = seen_domains.get(dom, 0) + 1
        out.append(hit)
        if len(out) >= max_total:
            return out
    return out


def _domain(url: str) -> str:
    """Hostname, lowercased, with a leading 'www.' removed.

    Was `host.lstrip("www.")`, which strips leading CHARACTERS in {w, .} rather
    than the prefix: wikipedia.org -> "ikipedia.org", who.int -> "ho.int",
    washingtonpost.com -> "ashingtonpost.com". The visible casualty was the junk
    blocklist — "wikihow.com" became "ikihow.com" and never matched.
    """
    try:
        host = urlparse(url).hostname or ""
        return host.lower().removeprefix("www.") if host else ""
    except Exception:
        return ""


# =============================================================================
# STEP 3: FETCH + EXTRACT
# =============================================================================

def fetch_and_clean(url: str, max_chars: int) -> str:
    """Fetch a page and return cleaned text content."""
    if not _BROWSER_AVAILABLE:
        return ""
    try:
        r = _ab_browse(url)
        if not isinstance(r, dict) or not r.get("success", True):
            return ""
        text = r.get("text") or r.get("content") or r.get("body") or ""
        text = _clean_page_text(str(text))
        return text[:max_chars]
    except Exception as e:
        return ""


def fetch_rendered(url: str, max_chars: int) -> str:
    """Re-fetch a page through a real browser so JavaScript actually runs.

    A plain HTTP fetch of a JS-rendered page returns the empty shell — that is
    exactly how a Facebook post yielded 116 characters and still got cited.
    Slower (seconds, not milliseconds), so this is a rescue attempt for pages
    the fast path failed on, never the default. Returns "" on any failure.
    """
    try:
        r = _ab_browse(url, js=True)
        if not isinstance(r, dict) or not r.get("success", True):
            return ""
        text = r.get("text") or r.get("content") or r.get("body") or ""
        return _clean_page_text(str(text))[:max_chars]
    except Exception:
        return ""


def _prefer_citable(sources: List[Dict]) -> List[Dict]:
    """Drop sources too thin to cite — unless they are all we have.

    Something beats nothing, but a page that gave us one sentence must never
    displace a page that gave us the article.
    """
    citable = [s for s in sources if _is_citable(s.get("text"))]
    return citable if citable else sources


def _clean_page_text(text: str) -> str:
    """Light cleanup — strip boilerplate-ish repeated short lines."""
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    # Drop obvious nav / cookie lines
    bad_substrings = (
        "accept cookies", "cookie policy", "sign in to continue",
        "subscribe now", "follow us on", "share this article",
    )
    lines = []
    for ln in text.splitlines():
        lnl = ln.strip().lower()
        if any(b in lnl for b in bad_substrings) and len(ln) < 120:
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


_EXTRACT_SYSTEM = """You extract the factually relevant passages from a web page that answer
a specific sub-query. Output ONLY JSON:
{
  "relevant": true/false,
  "extract":  "the 2-5 sentences most directly answering the sub-query, verbatim where possible",
  "confidence": "high | medium | low"
}

Rules:
- If the page is irrelevant, spam, or contains no useful info, set relevant=false and leave extract empty.
- DO NOT invent facts. Only report what is in the page.
- Keep extract under 500 words.
"""


def extract_from_page(sub_query: str, page_text: str, title: str) -> Dict:
    if not page_text or len(page_text) < 100:
        # A real verdict: the page had nothing. Not a failure, so not degraded.
        return {"relevant": False, "extract": "", "confidence": "low",
                "degraded": False}
    prompt = (
        f'SUB-QUERY: {sub_query}\n\nPAGE TITLE: {title}\n\n'
        f'PAGE CONTENT:\n{page_text[:4500]}\n\n'
        f'Extract the passages answering the sub-query.'
    )
    # Cascade: cheap 8B extractor first; fall back to model_selector / smart model.
    parsed = None
    raw = _extract_llm(prompt, _EXTRACT_SYSTEM)
    if raw:
        parsed = _parse_json_loose(raw)
    if not isinstance(parsed, dict):
        if ms:
            parsed = ms.call_json("extractor", prompt, system=_EXTRACT_SYSTEM)
        else:
            parsed = _parse_json_loose(call_llm_batch(prompt, system=_EXTRACT_SYSTEM))

    if not isinstance(parsed, dict):
        # The extractor did not answer (rate limit, bad JSON, provider down).
        # That is NOT the same as judging the page irrelevant, and must not be
        # reported as such — a 429 was silently deleting good sources.
        return {"relevant": False, "extract": "", "confidence": "low",
                "degraded": True}
    return {
        "relevant":   bool(parsed.get("relevant", False)),
        "extract":    str(parsed.get("extract", ""))[:2500],
        "confidence": str(parsed.get("confidence", "low")).lower(),
        "degraded":   False,
    }


def _recover_degraded(ex_res: Dict, src: Dict) -> Dict:
    """Fall back to the page's own text when the extractor could not run.

    Keeps a source in the evidence base at reduced confidence instead of
    dropping it. A healthy extract, or a genuine "not relevant" verdict from a
    model that actually ran, is returned untouched.
    """
    if not ex_res.get("degraded"):
        return ex_res
    raw = (src.get("text") or "").strip()
    if not raw:
        return ex_res
    return {"relevant": True, "extract": raw[:1500],
            "confidence": "low", "degraded": True}


# =============================================================================
# STEP 4: CROSS-REFERENCE
# =============================================================================

_CROSSREF_SYSTEM = """You are a careful fact-checker. Given extracts from multiple sources,
identify any contradictions or disputed claims. Output ONLY JSON:
{
  "contradictions": [
    {
      "claim":   "the disputed claim",
      "sources": ["source_id_1", "source_id_2"],
      "note":    "what they disagree on"
    }
  ]
}

If there are no contradictions, output {"contradictions": []}.

Flag ONLY direct factual disagreement — two sources stating incompatible things
about the same fact (different dates, numbers, names, outcomes).

Do NOT flag:
- a fact that appears in one source and is simply absent from another. Silence
  is not disagreement, and this is the most common false positive.
- different levels of detail, wording, emphasis or framing.
- one source covering a subtopic another does not mention.

If you are not pointing at two specific conflicting statements, output nothing.
Most source sets contain no contradictions; an empty list is the normal answer.
"""


def cross_reference(extracts: List[Dict]) -> List[Dict]:
    if len(extracts) < 2:
        return []
    sources_text = "\n\n".join(
        f'[{e["source_id"]}] {e["extract"][:800]}'
        for e in extracts if e.get("extract")
    )
    if not sources_text:
        return []
    prompt = f"Check the following extracts for contradictions:\n\n{sources_text}"
    # Cascade: cheap 8B first; fall back to model_selector / smart model.
    parsed = None
    raw = _extract_llm(prompt, _CROSSREF_SYSTEM)
    if raw:
        parsed = _parse_json_loose(raw)
    if not isinstance(parsed, dict):
        if ms:
            parsed = ms.call_json("reasoner", prompt, system=_CROSSREF_SYSTEM)
        else:
            parsed = _parse_json_loose(call_llm_batch(prompt, system=_CROSSREF_SYSTEM))

    if not isinstance(parsed, dict):
        return []
    contras = parsed.get("contradictions", [])
    return contras if isinstance(contras, list) else []


# =============================================================================
# STEP 5: SYNTHESISE
# =============================================================================

_SYNTH_SYSTEM = """You are Ultron-J's research synthesiser. You produce a clear, well-cited
answer from extracts of multiple sources.

Rules for the answer:
- Start with a direct 1-2 sentence answer.
- Then expand with the details, using numbered citations [1], [2] etc.
- Every factual claim MUST have a citation. If something came from a single
  source only, cite that source.
- If sources disagree, say so and cite both: "[1] says X but [3] claims Y".
- Keep under ~350 words unless the user's question obviously needs more.
- Use markdown (headings OK if the answer is long).
- Do NOT include a "Sources:" list — the caller adds that from metadata.
"""


def synthesise(question: str, extracts: List[Dict], contradictions: List[Dict]) -> str:
    relevant = [e for e in extracts if e.get("relevant") and e.get("extract")]
    if not relevant:
        return "I couldn't find sources that directly answer this question."

    src_block = "\n\n".join(
        f'[{e["source_id"]}] ({e["url"]})\n{e["extract"]}'
        for e in relevant
    )
    contra_block = ""
    if contradictions:
        contra_block = (
            "\n\nKNOWN CONTRADICTIONS (reflect these in your answer):\n"
            + json.dumps(contradictions, indent=2)[:1000]
        )

    prompt = (
        f"USER QUESTION: {question}\n\n"
        f"EXTRACTED EVIDENCE:\n{src_block}\n"
        f"{contra_block}\n\n"
        f"Write the answer now."
    )
    # Synthesis is the final answer — it must not come back empty. Try the
    # model_selector route, then fall back to a direct smart-model call, with
    # one retry, so a transient free-tier rate-limit (429) doesn't wipe the
    # whole research result.
    if ms:
        out = (ms.call("synthesise", prompt, system=_SYNTH_SYSTEM) or "").strip()
        if out:
            return out
    for _attempt in range(2):
        out = (call_llm_batch(prompt, system=_SYNTH_SYSTEM) or "").strip()
        if out:
            return out
        time.sleep(2.0)
    return (
        "I gathered and read the sources below, but the language model was rate-"
        "limited while writing the final summary. Please try again in a moment — "
        "the sources are listed so you can read them directly meanwhile."
    )


# =============================================================================
# MAIN RESEARCH FUNCTION
# =============================================================================

def research(
    question: str,
    depth: str = "standard",
    skip_cache: bool = False,
) -> Dict:
    """Full research pipeline."""
    t0 = time.time()
    cfg = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["standard"])

    # ── Cache check ──
    if not skip_cache and _VSTORE_AVAILABLE:
        prior = vector_store.find_prior_research(question, n=1)
        if prior and prior[0]["score"] > 0.75:
            return {
                "answer":         prior[0]["text"],
                "sources":        prior[0].get("metadata", {}).get("sources", []),
                "sub_queries":    [],
                "contradictions": [],
                "cached":         True,
                "ms":             int((time.time() - t0) * 1000),
            }

    # ── Step 1: Decompose ──
    sub_queries = decompose(question, max_subqueries=cfg["n_subqueries"])

    # ── Step 2: Search each sub-query in parallel ──
    all_hits: List[Dict] = []
    hits_per_sub: Dict[str, List[Dict]] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(sub_queries) or 1)) as ex:
        futures = {ex.submit(search_one, sq, cfg["pages_per_q"] * 2): sq for sq in sub_queries}
        for fut in as_completed(futures):
            sq = futures[fut]
            try:
                hits_per_sub[sq] = fut.result() or []
                all_hits.extend(hits_per_sub[sq])
            except Exception:
                hits_per_sub[sq] = []

    # ── Step 3: Select top-quality sources across all sub-queries ──
    diversified = diversify_sources(all_hits, max_total=cfg["pages_per_q"] * len(sub_queries))
    if not diversified:
        return {
            "answer":         "No search results available — check your internet connection or SearXNG.",
            "sources":        [],
            "sub_queries":    sub_queries,
            "contradictions": [],
            "cached":         False,
            "ms":             int((time.time() - t0) * 1000),
        }

    # ── Step 4: Fetch pages in parallel ──
    sources: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(6, len(diversified))) as ex:
        fut_map = {
            ex.submit(fetch_and_clean, h["url"], cfg["max_chars_per_page"]): h
            for h in diversified
        }
        for fut in as_completed(fut_map):
            hit = fut_map[fut]
            try:
                text = fut.result()
            except Exception:
                text = ""
            # A thin result usually means the page rendered its content with
            # JavaScript and the fast fetch got the empty shell. Retry those
            # through a real browser before settling for the search snippet.
            if not _is_citable(text):
                rendered = fetch_rendered(hit["url"], cfg["max_chars_per_page"])
                if len(rendered or "") > len(text or ""):
                    text = rendered
            # Last resort: the search engine's own pre-extracted snippet. Still
            # grounded text, better than dropping the source entirely — but
            # _prefer_citable below stops it displacing a real page.
            if not _is_citable(text):
                snippet = (hit.get("snippet") or "").strip()
                if len(snippet) > len(text or ""):
                    text = snippet
            if text and len(text) > 80:
                sources.append({
                    "source_id": f"S{len(sources) + 1}",
                    "url":       hit["url"],
                    "title":     hit.get("title", ""),
                    "domain":    _domain(hit["url"]),
                    "text":      text,
                })

    # A page that gave us one sentence must not displace one that gave us the
    # whole article. Re-number afterwards so citation ids stay contiguous.
    sources = _prefer_citable(sources)
    for _i, _s in enumerate(sources, 1):
        _s["source_id"] = f"S{_i}"

    if not sources:
        return {
            "answer":         "Found search results but couldn't fetch any page content.",
            "sources":        [{"url": h["url"], "title": h.get("title")} for h in diversified],
            "sub_queries":    sub_queries,
            "contradictions": [],
            "cached":         False,
            "ms":             int((time.time() - t0) * 1000),
        }

    # ── Step 5: Extract per sub-query ──
    # Best sub-query for each source = whichever yields the most relevant extract.
    # Practically: pair each source with the sub-query most similar in keywords,
    # but we skip that complexity — extract with the ORIGINAL question since
    # that's what actually needs answering.
    extracts: List[Dict] = []
    with ThreadPoolExecutor(max_workers=min(4, len(sources))) as ex:
        fut_map = {
            ex.submit(extract_from_page, question, s["text"], s["title"]): s
            for s in sources
        }
        for fut in as_completed(fut_map):
            src = fut_map[fut]
            try:
                ex_res = fut.result()
            except Exception:
                ex_res = {"relevant": False, "extract": "", "confidence": "low",
                          "degraded": True}
            ex_res = _recover_degraded(ex_res, src)
            extracts.append({**ex_res, **{
                "source_id": src["source_id"],
                "url":       src["url"],
                "title":     src["title"],
            }})

    # ── Step 6: Cross-reference (deep only) ──
    contradictions: List[Dict] = []
    if cfg["cross_ref"]:
        contradictions = cross_reference(extracts)

    # ── Step 7: Synthesise ──
    answer = synthesise(question, extracts, contradictions)

    # Re-number citations in the answer to 1..N for only the sources actually
    # referenced, and build the final source list.
    relevant_extracts = [e for e in extracts if e.get("relevant") and e.get("extract")]
    final_sources = _renumber_citations(answer, relevant_extracts)

    result = {
        "answer":         final_sources["answer"],
        "sources":        final_sources["sources"],
        "sub_queries":    sub_queries,
        "contradictions": contradictions,
        "cached":         False,
        "ms":             int((time.time() - t0) * 1000),
    }

    # ── Step 8: Cache ──
    if _VSTORE_AVAILABLE and result["answer"] and len(result["answer"]) > 80:
        try:
            vector_store.remember_research(
                query=question,
                summary=result["answer"],
                sources=[s["url"] for s in result["sources"]],
            )
        except Exception:
            pass

    return result


def _renumber_citations(answer: str, extracts: List[Dict]) -> Dict:
    r"""Rewrite [S1],[S2]... to [1],[2]... in order of appearance, and return the
    matching sources list.

    Handles GROUPED citations ("[1, 2, 3]", "[S2, S3]") as well as single ones.
    The old pattern was r"\[(S?\d+)\]", which matched "[1]" but not "[1, 2, 3]"
    — the form the synthesiser emits most often. Every id inside a group was
    invisible: never remapped, never added to sources. The visible symptom was
    an answer citing [1, 2, 3] that arrived with one source attached, so [2] and
    [3] pointed at nothing.
    """
    # A citation group: one or more S?N separated by commas, inside brackets.
    group_re = re.compile(r"\[\s*(S?\d+(?:\s*,\s*S?\d+)*)\s*\]")

    def _ids(group_body: str) -> List[str]:
        out = []
        for part in group_body.split(","):
            tag = part.strip()
            if not tag:
                continue
            if not tag.startswith("S"):
                tag = f"S{tag}"
            out.append(tag)
        return out

    known = {e["source_id"] for e in extracts}
    found_ids: List[str] = []
    for m in group_re.finditer(answer):
        for tag in _ids(m.group(1)):
            # Only cite sources we actually have — never invent one.
            if tag in known and tag not in found_ids:
                found_ids.append(tag)

    remap = {sid: str(i + 1) for i, sid in enumerate(found_ids)}

    def _sub(m):
        renumbered = [remap[t] for t in _ids(m.group(1)) if t in remap]
        if not renumbered:
            return ""  # a group naming only unknown sources cites nothing
        return "[" + ", ".join(renumbered) + "]"

    new_answer = group_re.sub(_sub, answer)

    sources = []
    for sid in found_ids:
        match = next((e for e in extracts if e["source_id"] == sid), None)
        if match:
            sources.append({
                "n":     int(remap[sid]),
                "url":   match["url"],
                "title": match["title"],
            })
    return {"answer": new_answer, "sources": sources}


# =============================================================================
# SMOKE TEST
# =============================================================================
if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What is Claude 4?"
    print(f"Researching: {q}\n")
    r = research(q, depth="quick")
    print(f"=== Answer ({r['ms']}ms, cached={r['cached']}) ===")
    print(r["answer"])
    print("\n=== Sources ===")
    for s in r["sources"]:
        print(f"  [{s['n']}] {s['title'][:60]} — {s['url']}")
    if r["contradictions"]:
        print("\n=== Contradictions ===")
        for c in r["contradictions"]:
            print(f"  - {c}")
