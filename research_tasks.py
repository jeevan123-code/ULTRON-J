"""
research_tasks.py — Web search / research handlers for Ultron's orchestrator.
Extracted from task_orchestrator.py to keep that file manageable.
"""
from typing import Dict


def handle_search_web(task: dict, text: str) -> Dict:
    """Cloud-only web search — does NOT open a browser."""
    query = task["params"][-1] if task["params"] else text
    try:
        from smart_browser_agent import cloud_search
        out     = cloud_search(query)
        summary = (out.get("summary") or "").strip()
        if out.get("success") and summary:
            return {
                "success":      True,
                "action_taken": "search_web",
                "message":      summary,
                "error":        "",
            }
        return {
            "success":      False,
            "action_taken": "search_web",
            "passthrough":  True,
            "message":      "",
            "error":        out.get("error", ""),
        }
    except Exception:
        return {"success": False, "action_taken": "search_web",
                "passthrough": True, "message": "", "error": ""}


def handle_search_on_site(task: dict) -> Dict:
    """Search a specific site via Tavily (cloud, no browser popup)."""
    try:
        from smart_browser_agent import cloud_search, is_known_site
        q = task["params"][0].strip() if task["params"] else ""
        s = task["params"][1].strip() if len(task["params"]) > 1 else None
        effective_site = s if (s and is_known_site(s)) else None
        if s and not effective_site:
            q = f"{q} {s}".strip()
        out   = cloud_search(q, effective_site)
        taken = "search_on_site" if effective_site else "search_web"
        return {
            "success":      bool(out.get("success")),
            "action_taken": taken,
            "message":      out.get("summary") or f"Searched '{q}' on {effective_site or 'web'}",
            "url":          out.get("url"),
            "error":        out.get("error", ""),
        }
    except Exception as e:
        return {"success": False, "error": str(e),
                "action_taken": "search_on_site",
                "message": f"Search failed: {e}"}


_BROWSER_NAMES = {"brave", "chrome", "firefox", "edge", "opera", "safari", "chromium"}


def handle_open_and_search(task: dict) -> Dict:
    """
    Open a site/browser and perform a search.
    Handles two cases:
      1. "open brave and search X"    → open Google in Brave browser
      2. "open youtube and search X"  → open YouTube search in default browser
    """
    try:
        from smart_browser_agent import search_and_summarize, build_search_url, SITE_URLS
        s   = (task["params"][0] or "").strip().lower() if task["params"] else "google"
        q   = (task["params"][1] or "").strip() if len(task["params"]) > 1 else ""

        if s in _BROWSER_NAMES:
            # User named a browser — open Google (or default search) in that browser
            site    = "google"
            browser = s
        else:
            # User named a site — open that site in the preferred browser
            site    = s
            browser = None

        url = build_search_url(q, site)
        try:
            from computer_control import open_url as _open_url
            _open_url(url, browser=browser)
        except Exception:
            import webbrowser as _wb
            _wb.open(url)

        # Scrape + summarize in background for the response
        import time as _time
        _time.sleep(2)
        try:
            from smart_browser_agent import search_and_scrape, summarize_with_llm
            scrape  = search_and_scrape(q, site)
            summary = summarize_with_llm(q, scrape.get("text", "")) if scrape.get("success") else ""
        except Exception:
            summary = ""

        used_browser = browser or "default browser"
        msg = summary or f"Opened {site} in {used_browser} and searched for '{q}'"
        return {
            "success":      True,
            "action_taken": "open_and_search",
            "message":      msg,
            "url":          url,
            "browser":      used_browser,
            "error":        "",
        }
    except Exception as e:
        return {"success": False, "error": str(e),
                "action_taken": "open_and_search",
                "message": f"Open-and-search failed: {e}"}
