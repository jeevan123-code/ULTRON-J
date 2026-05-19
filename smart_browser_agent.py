"""
smart_browser_agent.py — Open URL → scrape visible text → summarize.
Uses existing autonomous_browser if available; falls back to
requests + BeautifulSoup for simple cases.
"""
import time
import urllib.parse
from typing import Dict

SITE_URLS = {
    "google":     "https://www.google.com/search?q={q}",
    "youtube":    "https://www.youtube.com/results?search_query={q}",
    "chatgpt":    "https://chat.openai.com/?q={q}",
    "claude":     "https://claude.ai/new?q={q}",
    "perplexity": "https://www.perplexity.ai/?q={q}",
    "wiki":       "https://en.wikipedia.org/wiki/Special:Search?search={q}",
    "wikipedia":  "https://en.wikipedia.org/wiki/Special:Search?search={q}",
    "bing":       "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
}


def build_search_url(query: str, site: str = "google") -> str:
    q = urllib.parse.quote(query)
    template = SITE_URLS.get(site.lower(), SITE_URLS["google"])
    return template.format(q=q)


def search_and_scrape(query: str, site: str = "google") -> Dict:
    url = build_search_url(query, site)
    # Try existing autonomous_browser (Playwright-based) first
    try:
        from autonomous_browser import browse
        result = browse(url, js=True)
        if result.get("success"):
            text = (result.get("content") or "")[:3000]
            return {"success": True, "url": url, "text": text}
    except Exception:
        pass
    # Fallback: requests + BeautifulSoup
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.stripped_strings)[:3000]
        return {"success": True, "url": url, "text": text}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def summarize_with_llm(query: str, scraped_text: str) -> str:
    """Send scraped text + original query to LLM for short summary.

    stream_llm yields SSE-formatted strings ('data: {"token": "..."}\\n\\n'
    plus a final 'data: {"_full": "..."}\\n\\n'). Treating each chunk as
    plain text — the prior implementation — concatenated those SSE lines
    verbatim into the summary, which then leaked into the user-visible
    ``message`` field and would be spoken by TTS. Parse the stream
    properly: prefer ``_full`` if the server emitted it, otherwise
    accumulate ``token`` payloads."""
    try:
        from llm_engine import stream_llm
        import json as _json
        prompt = (
            f"User asked: {query}\n\n"
            f"Top web results:\n{scraped_text}\n\n"
            "Give a 2-3 sentence direct answer in plain English. "
            "Be concrete and specific. No filler."
        )
        full = None
        tokens = []
        for chunk in stream_llm(
                [{"role": "user", "content": prompt}], temperature=0.3):
            payload = None
            if isinstance(chunk, dict):
                payload = chunk
            elif isinstance(chunk, str):
                line = chunk.strip()
                if line.startswith("data:"):
                    body = line[5:].strip()
                    try:
                        payload = _json.loads(body)
                    except _json.JSONDecodeError:
                        payload = None
                else:
                    tokens.append(chunk)
                    continue
            if not isinstance(payload, dict):
                continue
            if "_full" in payload:
                full = payload["_full"]
            elif "token" in payload:
                tokens.append(payload["token"])
        text = full if full is not None else "".join(tokens)
        return text.strip()
    except Exception as e:
        return f"(summary failed: {e})"


def search_and_summarize(query: str, site: str = "google",
                         browser: str = None) -> Dict:
    """Full pipeline: open visually + scrape + summarize.
    Used ONLY by `open_and_search` (the user explicitly asked to open).
    Other paths should call cloud_search() so no browser pops up."""
    url = build_search_url(query, site)
    # Open browser visually for the user
    try:
        from computer_control import open_url
        open_url(url, browser=browser)
    except Exception:
        pass
    # Wait for page to load before scraping
    time.sleep(2)
    scrape = search_and_scrape(query, site)
    if not scrape.get("success"):
        return {"success": False, "error": scrape.get("error"), "url": url}
    summary = summarize_with_llm(query, scrape["text"])
    return {
        "success": True,
        "url":     url,
        "text":    scrape["text"][:500],
        "summary": summary,
    }


_DOMAIN_ALIASES = {
    "github":        "github.com",
    "stackoverflow":  "stackoverflow.com",
    "stack overflow": "stackoverflow.com",
    "youtube":       "youtube.com",
    "reddit":        "reddit.com",
    "wikipedia":     "wikipedia.org",
    "wiki":          "wikipedia.org",
    "medium":        "medium.com",
    "twitter":       "twitter.com",
    "x":             "x.com",
    "hacker news":   "news.ycombinator.com",
    "hn":            "news.ycombinator.com",
    "arxiv":         "arxiv.org",
    "pypi":          "pypi.org",
    "npm":           "npmjs.com",
    "mdn":           "developer.mozilla.org",
    "docs.python":   "docs.python.org",
    "python":        "docs.python.org",
}


def _resolve_site_to_domain(site: str):
    """Map a friendly site name to a real domain for Tavily include_domains.
    Returns None when the input is not recognizable as a site so callers can
    fall back to an unscoped web search instead of fabricating a domain
    (the previous ``<word>.com`` fallback turned natural-language tokens
    like 'hyderabad' into 'hyderabad.com' and broke Tavily scoping)."""
    if not site:
        return None
    s = site.strip().lower().rstrip("/")
    if not s or s in ("google", "bing", "duckduckgo", "web"):
        return None
    if s in _DOMAIN_ALIASES:
        return _DOMAIN_ALIASES[s]
    # Already a domain-shaped string ("github.com", "stackoverflow.com")
    if "." in s:
        return s
    return None


def is_known_site(site: str) -> bool:
    """True iff ``site`` is recognizable as a real site (alias or dotted
    domain). Used by the orchestrator to decide whether a regex hit on
    ``search X on/in <token>`` should stay as a site-scoped search or be
    demoted to a plain web search when ``<token>`` is just a noun."""
    return _resolve_site_to_domain(site) is not None


def cloud_search(query: str, site: str = None) -> Dict:
    """Cloud-only search — never opens a visible browser.
    Tries Tavily first with real include_domains scoping when a site is
    given, then falls back to a headless scrape of the search results
    page. Returns {success, summary, sources, url}.

    Used by the orchestrator for `search_web` / `search_on_site` so
    Jeevan can ask a question without Ultron popping a Chrome window.
    `open_and_search` (when he explicitly says "open") still uses
    search_and_summarize() above."""
    domain = _resolve_site_to_domain(site)
    # 1. Tavily with real domain scoping
    try:
        from app import search_web_tavily
        result = search_web_tavily(
            query,
            include_domains=[domain] if domain else None,
        )
        summary = (result.get("summary") or "").strip()
        sources = result.get("sources") or []
        if summary or sources:
            if not summary:
                snippets = []
                for s in sources[:3]:
                    title   = s.get("title", "")
                    content = (s.get("content") or "")[:240]
                    snippets.append(f"- {title}: {content}")
                summary = "\n".join(snippets) if snippets else f"Searched: {query}"
            return {
                "success": True,
                "summary": summary,
                "sources": sources[:5],
                "url":     None,
            }
    except Exception:
        pass
    # 2. Fallback — headless scrape of the search page (no visible window).
    try:
        scrape = search_and_scrape(query, site or "duckduckgo")
        if scrape.get("success"):
            summary = summarize_with_llm(query, scrape["text"])
            return {
                "success": True,
                "summary": summary,
                "sources": [],
                "url":     scrape.get("url"),
            }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}
    return {"success": False, "error": "Cloud search unavailable (no Tavily key + scrape failed)"}
