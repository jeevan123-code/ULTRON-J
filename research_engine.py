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
        search_searxng, search_duckduckgo, search_wikipedia,
    )
    _SEARCH_AVAILABLE = True
except ImportError:
    _SEARCH_AVAILABLE = False
    def search_searxng(q, max_results=5): return []
    def search_duckduckgo(q, max_results=5): return []
    def search_wikipedia(q): return ""

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

try:
    import vector_store
    _VSTORE_AVAILABLE = True
except ImportError:
    _VSTORE_AVAILABLE = False


# =============================================================================
# CONFIG
# =============================================================================

DEPTH_CONFIG = {
    "quick":    {"n_subqueries": 1, "pages_per_q": 2, "max_chars_per_page": 2500, "cross_ref": False},
    "standard": {"n_subqueries": 3, "pages_per_q": 3, "max_chars_per_page": 3500, "cross_ref": False},
    "deep":     {"n_subqueries": 4, "pages_per_q": 4, "max_chars_per_page": 5000, "cross_ref": True},
}

# Domains we down-weight (low quality / aggregator-only)
_LOW_QUALITY_DOMAINS = {
    "pinterest.com", "quora.com", "answers.yahoo.com",
    "reference.com", "wikihow.com",
}


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
    """Run one sub-query, merge SearXNG + DDG, dedupe by URL."""
    combined: Dict[str, Dict] = {}  # keyed by URL

    for hit in search_searxng(query, max_results=n_results) or []:
        url = (hit.get("url") or "").strip()
        if url:
            combined[url] = {
                "url":     url,
                "title":   hit.get("title", ""),
                "snippet": hit.get("snippet", ""),
                "origin":  "searxng",
            }

    if len(combined) < n_results:
        for hit in search_duckduckgo(query, max_results=n_results) or []:
            url = (hit.get("url") or "").strip()
            if url and url not in combined:
                combined[url] = {
                    "url":     url,
                    "title":   hit.get("title", ""),
                    "snippet": hit.get("snippet", ""),
                    "origin":  "ddg",
                }

    return list(combined.values())


def diversify_sources(all_hits: List[Dict], max_total: int = 10) -> List[Dict]:
    """Drop duplicate domains, demote low-quality ones. Returns up to max_total."""
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
    try:
        host = urlparse(url).hostname or ""
        return host.lower().lstrip("www.") if host else ""
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
        return {"relevant": False, "extract": "", "confidence": "low"}
    prompt = (
        f'SUB-QUERY: {sub_query}\n\nPAGE TITLE: {title}\n\n'
        f'PAGE CONTENT:\n{page_text[:4500]}\n\n'
        f'Extract the passages answering the sub-query.'
    )
    if ms:
        parsed = ms.call_json("extractor", prompt, system=_EXTRACT_SYSTEM)
    else:
        raw = call_llm_batch(prompt, system=_EXTRACT_SYSTEM)
        parsed = _parse_json_loose(raw)

    if not isinstance(parsed, dict):
        return {"relevant": False, "extract": "", "confidence": "low"}
    return {
        "relevant":   bool(parsed.get("relevant", False)),
        "extract":    str(parsed.get("extract", ""))[:2500],
        "confidence": str(parsed.get("confidence", "low")).lower(),
    }


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
Only flag real substantive disagreement on facts, not stylistic differences.
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
    if ms:
        parsed = ms.call_json("reasoner", prompt, system=_CROSSREF_SYSTEM)
    else:
        raw = call_llm_batch(prompt, system=_CROSSREF_SYSTEM)
        parsed = _parse_json_loose(raw)

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
    if ms:
        return ms.call("synthesise", prompt, system=_SYNTH_SYSTEM).strip()
    return call_llm_batch(prompt, system=_SYNTH_SYSTEM).strip()


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
            if text and len(text) > 200:
                sources.append({
                    "source_id": f"S{len(sources) + 1}",
                    "url":       hit["url"],
                    "title":     hit.get("title", ""),
                    "domain":    _domain(hit["url"]),
                    "text":      text,
                })

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
                ex_res = {"relevant": False, "extract": "", "confidence": "low"}
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
    """Rewrite [S1],[S2]... to [1],[2]... in the answer, in order of appearance,
    and return the matching sources list."""
    # Pattern matches [S1], [1], [S2]... — catch both styles the LLM might emit
    pattern = re.compile(r"\[(S?\d+)\]")
    found_ids = []
    for m in pattern.finditer(answer):
        tag = m.group(1)
        # Normalise both "S1" and "1" into "S1" form
        if not tag.startswith("S"):
            tag = f"S{tag}"
        if tag not in found_ids:
            found_ids.append(tag)

    # Build remap: S1 → 1, S3 → 2, etc.
    remap = {sid: str(i + 1) for i, sid in enumerate(found_ids)}

    # Apply remap to answer
    def _sub(m):
        tag = m.group(1)
        if not tag.startswith("S"):
            tag = f"S{tag}"
        return f"[{remap.get(tag, tag[1:])}]"

    new_answer = pattern.sub(_sub, answer)

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
