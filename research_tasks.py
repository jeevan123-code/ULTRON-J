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


def handle_open_and_search(task: dict) -> Dict:
    """Open a site and perform a search — cloud then browser fallback."""
    try:
        from smart_browser_agent import search_and_summarize
        s   = task["params"][0].strip() if task["params"] else "google"
        q   = task["params"][1].strip() if len(task["params"]) > 1 else ""
        out = search_and_summarize(q, s)
        return {
            "success":      bool(out.get("success")),
            "action_taken": "open_and_search",
            "message":      out.get("summary") or f"Opened {s} with search '{q}'",
            "url":          out.get("url"),
            "error":        out.get("error", ""),
        }
    except Exception as e:
        return {"success": False, "error": str(e),
                "action_taken": "open_and_search",
                "message": f"Open-and-search failed: {e}"}
