"""
brain_orchestrator.py — The JARVIS-like planner.

For complex user requests, this module:
  1. Decomposes the request into a DAG of sub-tasks (via LLM).
  2. Executes the DAG respecting dependencies.
  3. Routes each sub-task to the best provider (model_selector).
  4. Uses specialised handlers for known task kinds.
  5. Persists the graph so a crashed run can resume.
  6. Returns both the final answer AND the full reasoning trail.

Task kinds the orchestrator knows how to execute natively:
  - search        : web search via Tavily, falling back to local_smart_search
  - fetch_url     : fetch a page body via autonomous_browser or requests
  - research      : full research_engine call (multi-source, citation tracking)
  - recall        : query vector_store
  - summarise     : LLM summary of input
  - extract       : LLM extraction of a field from input
  - reason        : general LLM reasoning step
  - write_file    : create a file
  - llm           : generic LLM call with pass-through params
  - shell         : (DISABLED by default) shell command — needs explicit approval

Anything else is routed to `llm` with the params rendered into a prompt.

Integration: called from /ask when complexity=="COMPLEX" (see app.py patch).
"""

import json
import re
import time
import traceback
from typing import Dict, List, Optional, Any

from task_graph import TaskGraph, graph_from_plan, READY
try:
    import model_selector as ms
except ImportError:
    ms = None

# Optional imports — we degrade gracefully
try:
    from local_engine import local_smart_search
    _SEARCH_AVAILABLE = True
except ImportError:
    _SEARCH_AVAILABLE = False
    def local_smart_search(q): return ""

try:
    from autonomous_browser import browse as _ab_browse
    _BROWSER_AVAILABLE = True
except ImportError:
    _BROWSER_AVAILABLE = False
    def _ab_browse(url, js=False): return {"success": False, "content": ""}


def _search_web(query: str) -> str:
    """Web search for the `search` task kind — Tavily first, scrapers second.

    /ask, voice_routes and react_engine all try Tavily before falling back to
    the local scrape chain. This module used to go straight to that chain,
    whose backends are SearXNG (nothing, not self-hosted) and DuckDuckGo
    (answered 2 of 6 attempts when measured 2026-07-29) — so an orchestrator
    search failed most of the time while a working paid key sat unused.

    The app import is deferred because app.py imports this module.
    """
    try:
        from app import search_web_tavily
        sources = (search_web_tavily(query) or {}).get("sources") or []
        if sources:
            return "\n".join(
                f"• {s.get('title', '')}: {(s.get('content') or '')[:300]}"
                for s in sources[:4]
            )
    except Exception:
        pass  # any Tavily fault just means we fall through to the scrapers
    return local_smart_search(query) or ""


def fetch_page_content(url: str, max_chars: int = 6000) -> str:
    """Thin wrapper around autonomous_browser.browse → returns string content."""
    try:
        r = _ab_browse(url)
        if not isinstance(r, dict):
            return ""
        # autonomous_browser returns different keys in different code paths — try all
        text = r.get("content") or r.get("text") or r.get("body") or r.get("html") or ""
        return str(text)[:max_chars]
    except Exception:
        return ""

try:
    import vector_store
    _VSTORE_AVAILABLE = True
except ImportError:
    _VSTORE_AVAILABLE = False

try:
    from llm_engine import call_llm_batch
except ImportError:
    def call_llm_batch(p, **kw): return ""


# =============================================================================
# PLANNING PROMPT
# =============================================================================

_PLANNER_SYSTEM = """You are Ultron-J's planning brain. You take a user request and output a
JSON task graph of concrete steps. Each step is a small, independently-executable
sub-task.

Output format — ONLY this JSON, no prose:
{
  "reasoning": "one or two sentences on why you chose this plan",
  "plan": [
    {
      "id": "s1",
      "kind": "search | fetch_url | research | recall | summarise | extract | reason | write_file | llm",
      "description": "what this step does",
      "params": { ... kind-specific inputs ... },
      "depends_on": [],
      "agent": "default"
    },
    { "id": "s2", ... , "depends_on": ["s1"] }
  ]
}

Rules:
- IDs must be short strings like "s1", "s2".
- depends_on lists the ids this step needs. Earlier results can be referenced
  in params with "{s1}" which will be replaced by s1's result at run time.
- Keep plans SHORT — 2 to 6 steps. More is rarely better.
- If the request is trivial (greeting, arithmetic), output {"plan": []} so the
  caller falls back to the direct LLM path.
- Prefer "research" for anything that needs multi-source web lookup with citations.
  Prefer "search" for one-shot quick lookups.
- Use "recall" at the START of research-heavy plans to check if we've done this
  work before.
- The FINAL step should almost always be a "summarise" or "reason" that produces
  the user-facing answer.
"""


def plan_request(user_request: str, context: str = "") -> Dict:
    """Call the LLM to produce a DAG plan.

    Returns {"reasoning": ..., "plan": [...]} (plan may be [] for trivial reqs).
    """
    prompt = f"USER REQUEST: {user_request.strip()}\n\n"
    if context:
        prompt += f"RELEVANT CONTEXT:\n{context[:2000]}\n\n"
    prompt += "Produce the JSON task graph now."

    if ms:
        parsed = ms.call_json("planner", prompt, system=_PLANNER_SYSTEM)
    else:
        raw = call_llm_batch(prompt, system=_PLANNER_SYSTEM, provider="gemini")
        parsed = _safe_json(raw)

    if not isinstance(parsed, dict):
        return {"reasoning": "planner returned unparseable output", "plan": []}
    plan = parsed.get("plan", [])
    if not isinstance(plan, list):
        plan = []
    return {
        "reasoning": str(parsed.get("reasoning", ""))[:500],
        "plan": plan,
    }


def _safe_json(raw: str) -> Optional[Dict]:
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
# TASK EXECUTION
# =============================================================================

def execute_task(task: Dict, resolved_params: Dict) -> Any:
    """Run one task and return its result. Raises on failure.

    resolved_params contains the task's params with {id} placeholders already
    substituted and a _deps dict with raw predecessor results.
    """
    kind = task["kind"]
    p = resolved_params or {}

    if kind == "search":
        query = p.get("query") or p.get("q") or task.get("description", "")
        result = _search_web(query)
        if not result and not _SEARCH_AVAILABLE:
            return {"error": "search unavailable", "query": query}
        return {"query": query, "results": result[:4000]}

    if kind == "fetch_url":
        url = p.get("url") or ""
        if not url or not _BROWSER_AVAILABLE:
            return {"error": "fetch unavailable or no url", "url": url}
        try:
            content = fetch_page_content(url, max_chars=6000)
        except Exception as e:
            return {"error": str(e)[:200], "url": url}
        return {"url": url, "content": content or ""}

    if kind == "research":
        try:
            from research_engine import research
        except ImportError:
            return {"error": "research_engine not available"}
        question = p.get("question") or p.get("query") or task.get("description", "")
        return research(question, depth=p.get("depth", "standard"))

    if kind == "recall":
        if not _VSTORE_AVAILABLE:
            return {"error": "vector_store unavailable", "hits": []}
        query = p.get("query") or task.get("description", "")
        hits = vector_store.recall(query, n=p.get("n", 5), kind=p.get("kind"))
        return {"query": query, "hits": hits}

    if kind == "summarise":
        text = p.get("text") or ""
        # Pull from deps if text wasn't set
        if not text and p.get("_deps"):
            text = "\n\n".join(str(v)[:3000] for v in p["_deps"].values())
        if not text:
            return {"error": "nothing to summarise"}
        sys = "You summarise the input concisely and accurately. Output only the summary."
        prompt = f"Summarise the following in at most 6 bullet points:\n\n{text[:6000]}"
        out = ms.call("summarise", prompt, system=sys) if ms else call_llm_batch(prompt, system=sys)
        return {"summary": out.strip()}

    if kind == "extract":
        field = p.get("field") or "main_points"
        text = p.get("text") or ""
        if not text and p.get("_deps"):
            text = "\n\n".join(str(v)[:3000] for v in p["_deps"].values())
        sys = "Extract the requested field. Output only the extracted content."
        prompt = f"From the following text, extract: {field}\n\n{text[:6000]}"
        out = ms.call("extractor", prompt, system=sys) if ms else call_llm_batch(prompt, system=sys)
        return {"field": field, "value": out.strip()}

    if kind in ("reason", "llm"):
        prompt = p.get("prompt") or task.get("description", "")
        if p.get("_deps"):
            dep_text = "\n\n".join(
                f"[{did}] {str(v)[:2500]}" for did, v in p["_deps"].items()
            )
            prompt = f"{prompt}\n\nPRIOR STEP RESULTS:\n{dep_text}"
        sys = p.get("system", "")
        out = ms.call("reasoner" if kind == "reason" else "default", prompt, system=sys) \
              if ms else call_llm_batch(prompt, system=sys)
        return {"output": out.strip()}

    if kind == "write_file":
        path = p.get("path")
        content = p.get("content", "")
        if not path:
            return {"error": "no path"}
        if p.get("_deps") and not content:
            content = "\n\n".join(str(v) for v in p["_deps"].values())
        try:
            import os as _os
            _os.makedirs(_os.path.dirname(_os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(content))
            return {"path": path, "bytes": len(str(content))}
        except Exception as e:
            return {"error": str(e), "path": path}

    if kind == "shell":
        cmd = p.get("cmd", "")
        if not cmd:
            return {"error": "no shell command"}
        # Approval gate. Callers can bypass by setting approved=True (e.g. a
        # pre-confirmed staged command). Otherwise route through human_interface
        # so Jeevan approves from /ultimate/approval/*. Timeout or denial → refuse.
        if not p.get("approved"):
            try:
                import human_interface as _hi
                req_id = _hi.request_approval(
                    kind="shell",
                    summary=f"Run shell command: {cmd[:200]}",
                    details={"cmd": cmd, "source": "brain_orchestrator"},
                    timeout_sec=60,
                    risk_level="high",
                )
                decision = _hi.wait_for_approval(req_id, timeout=60)
                if decision != "approved":
                    return {"error": f"shell command not approved ({decision})", "cmd": cmd}
            except ImportError:
                return {"error": "shell commands require explicit approval (human_interface unavailable)"}
            except Exception as e:
                return {"error": f"approval flow failed: {e}", "cmd": cmd}
        import subprocess
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return {"stdout": r.stdout[-3000:], "stderr": r.stderr[-1000:], "code": r.returncode}
        except Exception as e:
            return {"error": str(e)}

    # Unknown kind: fall through to generic llm call
    prompt = f"Perform this task: {task.get('description', kind)}\n\nParams: {json.dumps(p, default=str)[:2000]}"
    out = ms.call("default", prompt) if ms else call_llm_batch(prompt)
    return {"kind": kind, "output": out.strip()}


# =============================================================================
# GRAPH EXECUTOR
# =============================================================================

def execute_graph(graph: TaskGraph, max_parallel: int = 1) -> Dict:
    """Run a TaskGraph to completion. Returns a summary with results.

    max_parallel=1 runs sequentially (safer for local-LLM setups); bump it up
    once the rest of the system is solid.
    """
    import concurrent.futures as cf

    trail: List[Dict] = []

    while not graph.done():
        ready = graph.ready_tasks()
        if not ready:
            # deadlock — everything either completed, failed, or stuck
            break

        # Execute (in parallel if requested)
        to_run = ready[:max_parallel] if max_parallel > 1 else ready[:1]

        def _run_one(task):
            tid = task["id"]
            graph.start(tid)
            resolved = graph.get_input(tid)
            try:
                result = execute_task(task, resolved)
                graph.complete(tid, result)
                return {"id": tid, "kind": task["kind"], "ok": True, "result": result}
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                graph.fail(tid, err)
                return {"id": tid, "kind": task["kind"], "ok": False, "error": err,
                        "traceback": traceback.format_exc()[:800]}

        if max_parallel > 1 and len(to_run) > 1:
            with cf.ThreadPoolExecutor(max_workers=max_parallel) as ex:
                for res in ex.map(_run_one, to_run):
                    trail.append(res)
        else:
            for t in to_run:
                trail.append(_run_one(t))

        graph.save()

    # Collect leaves — those are the user-facing outputs
    final_results = graph.leaf_results()
    # If the final step looks like a summary/reasoning step, pluck its string
    answer = _extract_answer(final_results)

    return {
        "graph_id":  graph.id,
        "goal":      graph.goal,
        "answer":    answer,
        "trail":     trail,
        "summary":   graph.summary(),
    }


def _extract_answer(leaf_results: List[Any]) -> str:
    if not leaf_results:
        return ""
    for r in leaf_results:
        if isinstance(r, dict):
            for k in ("summary", "output", "answer", "value", "content"):
                if k in r and r[k]:
                    return str(r[k]).strip()
    # fallback: join everything
    return "\n\n".join(str(r)[:2000] for r in leaf_results)


# =============================================================================
# PUBLIC ENTRYPOINT
# =============================================================================

def orchestrate(user_request: str, context: str = "") -> Dict:
    """Full pipeline: plan → build graph → execute → return answer + trail.

    Call this from app.py when complexity == COMPLEX or when explicit planning
    is requested ("kartha plan this:", "think carefully", etc.).
    """
    plan = plan_request(user_request, context=context)
    steps = plan.get("plan") or []

    if not steps:
        # Planner said trivial — caller should use the normal LLM path
        return {
            "used_planner": False,
            "reasoning":    plan.get("reasoning", ""),
            "answer":       "",
            "graph_id":     None,
        }

    graph = graph_from_plan(user_request, steps)
    graph.save()
    result = execute_graph(graph)
    result["used_planner"] = True
    result["reasoning"] = plan.get("reasoning", "")
    result["plan"] = steps
    return result


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "Research vector databases and write me a 3-paragraph summary."
    r = orchestrate(q)
    print(json.dumps(r, indent=2, default=str)[:3000])
