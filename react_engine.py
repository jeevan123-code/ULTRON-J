"""
react_engine.py — ReAct Reasoning Engine for Ultron-J Intelligence Core.
THE CORE PROBLEM THIS SOLVES:
─────────────────────────────────────────────────────────────────
Right now Ultron answers in one shot:
  [question] → [LLM] → [answer]
That's a reflex, not intelligence. Jarvis REASONED.
This engine makes the LLM go through a real thinking process:
  1. THINK — What is being asked? What do I already know?
  2. PLAN  — What information do I need to answer well?
  3. ACT   — Use tools: search, recall, calculate, check screen
  4. OBSERVE — What did I learn from the tool result?
  5. THINK — Is this enough? Do I need more?
  6. ANSWER — Now deliver the best possible response
For complex queries, this runs up to MAX_ITERATIONS times.
For simple queries, it generates chain-of-thought and answers directly.
TOOL SUPPORT:
─────────────────────────────────────────────────────────────────
The LLM can call these tools during reasoning:
  web_search    — Search the web for current information
  recall_memory — Search Ultron's memory for relevant past context
  calculate     — Evaluate a mathematical expression
  get_weather   — Get current Hyderabad weather
  check_screen  — See what's currently on Jeevan's screen
─────────────────────────────────────────────────────────────────
Author: Jeevan's Ultron-J Intelligence Core
"""
import json
import os
import re
import requests
import threading
from typing import Generator, Optional, Tuple

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Max tool-use iterations before forcing a final answer
MAX_ITERATIONS = 4

# Max tokens for reasoning phase (batch call)
REASONING_MAX_TOKENS = 1200

# Groq model for reasoning
INTELLIGENCE_MODEL = "llama-3.3-70b-versatile"


# =============================================================================
# COMPLEXITY CLASSIFIER
# =============================================================================
def classify_complexity(question: str) -> str:
    """
    Classify a question as SIMPLE / MEDIUM / COMPLEX.
    SIMPLE  → No reasoning needed. Direct answer from world state.
    MEDIUM  → Needs chain-of-thought but no tool calls.
    COMPLEX → Needs multi-step reasoning and possibly tool calls.
    """
    q = question.lower().strip()
    words = q.split()

    # Very short questions are almost always simple
    if len(words) <= 4:
        return "SIMPLE"

    # Pattern matches for SIMPLE
    simple_patterns = [
        "what time", "what day", "what date", "today's date",
        "how are you", "your mood", "your energy",
        "weather", "temperature", "status",
        "what is your", "who are you",
        "hello", "hi ", "hey ", "good morning", "good evening",
    ]
    if any(p in q for p in simple_patterns):
        return "SIMPLE"

    # Pattern matches for COMPLEX — needs deep reasoning or tools
    complex_patterns = [
        "analyze", "analysis", "breakdown", "break down",
        "compare", "comparison", "versus", " vs ",
        "explain why", "explain how", "why does", "how does",
        "step by step", "in detail", "thoroughly",
        "what should i", "should i", "help me decide",
        "pros and cons", "tradeoffs", "trade-offs",
        "review my", "review this", "check this",
        "research", "find out", "investigate",
        "plan for", "strategy for", "roadmap",
        "debug", "fix this", "what's wrong",
        "optimize", "improve", "refactor",
        "write a ", "create a ", "design a ", "build a ",
        "help me think", "think through",
        "what do you think about",
        "is it possible", "can i ", "how can i",
        "what are the", "what would", "what could",
    ]
    if any(p in q for p in complex_patterns):
        return "COMPLEX"

    # Medium for longer questions
    if len(words) > 12:
        return "MEDIUM"

    return "MEDIUM"


# =============================================================================
# DIRECT GROQ BATCH CALL (bypasses streaming for reasoning phase)
# =============================================================================
def _call_intelligence_batch(messages: list, max_tokens: int = REASONING_MAX_TOKENS,
                             provider: str = None) -> str:
    """
    Batch call to the reasoning LLM. Honors the user's provider pick from the
    /ask dropdown so the COMPLEX-question path doesn't silently pin every reply
    to Groq.

      provider=None | "" | "auto" | "groq" → fast direct Groq path (default)
      provider="gemini" | "openrouter"    → route through llm_engine.call_llm_batch
                                            so the chosen cloud actually answers
    """
    _prov = (provider or "").lower().strip()

    # User explicitly picked a non-Groq cloud — route the reasoning batch through
    # llm_engine.call_llm_batch so their dropdown choice is honored. We pass the
    # full conversation as the "user" content because call_llm_batch only takes
    # a single prompt; the system block is preserved separately.
    if _prov in ("gemini", "openrouter"):
        try:
            from llm_engine import call_llm_batch
            system_msg = ""
            user_blocks = []
            for m in messages:
                if not isinstance(m, dict):
                    continue
                role = m.get("role", "")
                content = m.get("content", "")
                if role == "system" and not system_msg:
                    system_msg = content
                else:
                    user_blocks.append(f"{role.upper()}: {content}")
            user_prompt = "\n\n".join(user_blocks) if user_blocks else ""
            return call_llm_batch(user_prompt, system=system_msg, provider=_prov) or ""
        except Exception:
            return ""

    try:
        from config import GROQ_KEYS, GROQ_URL, get_next_key
        if not GROQ_KEYS:
            raise ValueError("No Groq keys")

        key = get_next_key("groq", GROQ_KEYS)
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": INTELLIGENCE_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.3,  # Lower temp for reasoning
                "stream": False,
            },
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        # Fallback to existing engine
        try:
            from llm_engine import call_llm_batch
            system = messages[0]["content"] if messages and messages[0].get("role") == "system" else ""
            user = messages[-1]["content"] if messages else ""
            return call_llm_batch(user, system=system)
        except Exception:
            return ""


# =============================================================================
# TOOL EXECUTION
# =============================================================================
def _execute_tool(tool_name: str, tool_input: str) -> str:
    """
    Execute a tool call and return the result as a string.
    All tools fail gracefully.

    Safe-only by design: ReAct can READ state but cannot mutate it.
    Destructive actions (delete_*, write/append/rename/move/copy, run_command,
    send_email, type_text, click, hotkey, press_key, set_clipboard) are
    intentionally NOT exposed — those must go through orchestrate's picker
    so the user gets the yes/cancel confirmation gate.
    """
    tool_name = tool_name.strip().lower()

    # Original tools
    if tool_name == "web_search":
        return _tool_web_search(tool_input.strip())
    elif tool_name == "recall_memory":
        return _tool_recall_memory(tool_input.strip())
    elif tool_name == "calculate":
        return _tool_calculate(tool_input.strip())
    elif tool_name == "get_weather":
        return _tool_get_weather()
    elif tool_name == "check_screen":
        return _tool_check_screen()

    # New safe action_engine tools (Phase 2)
    elif tool_name == "file_list":
        return _tool_file_list(tool_input.strip())
    elif tool_name == "file_read":
        return _tool_file_read(tool_input.strip())
    elif tool_name == "get_clipboard":
        return _tool_get_clipboard()
    elif tool_name == "get_window":
        return _tool_get_window()
    elif tool_name == "web_scrape":
        return _tool_web_scrape(tool_input.strip())
    elif tool_name == "git_status":
        return _tool_git_status(tool_input.strip())
    elif tool_name == "screenshot":
        return _tool_screenshot()

    else:
        return f"Unknown tool: {tool_name}"


def _ae(action: str, **params) -> dict:
    """Thin call into action_engine. Returns {} on import error."""
    try:
        from action_engine import execute_action
        return execute_action(action, params)
    except Exception as e:
        return {"success": False, "error": f"action_engine import failed: {e}"}


def _tool_file_list(path: str) -> str:
    if not path:
        return "file_list needs a path."
    out = _ae("file_list", path=path)
    if out.get("success"):
        return f"file_list({path}):\n{out.get('result','')[:1500]}"
    return f"file_list failed: {out.get('error','unknown')}"


def _tool_file_read(path: str) -> str:
    if not path:
        return "file_read needs a path."
    out = _ae("file_read", path=path)
    if out.get("success"):
        return f"file_read({path}):\n{out.get('result','')[:2500]}"
    return f"file_read failed: {out.get('error','unknown')}"


def _tool_get_clipboard() -> str:
    out = _ae("get_clipboard")
    if out.get("success"):
        return f"Clipboard:\n{(out.get('result') or '')[:1500]}"
    return f"Clipboard unavailable: {out.get('error','unknown')}"


def _tool_get_window() -> str:
    out = _ae("get_window")
    if out.get("success"):
        return f"Active window: {out.get('result','')}"
    return f"get_window failed: {out.get('error','unknown')}"


def _tool_web_scrape(url: str) -> str:
    if not url:
        return "web_scrape needs a URL."
    out = _ae("web_scrape", url=url)
    if out.get("success"):
        return f"Page content ({url}):\n{(out.get('result') or '')[:2500]}"
    return f"web_scrape failed: {out.get('error','unknown')}"


def _tool_git_status(path: str) -> str:
    out = _ae("git_status", path=path or ".")
    if out.get("success"):
        return f"git_status({path or '.'}):\n{(out.get('result') or '')[:1500]}"
    return f"git_status failed: {out.get('error','unknown')}"


def _tool_screenshot() -> str:
    """Take a screenshot and return where it was saved (no Save-As dialog)."""
    try:
        from computer_control import take_screenshot
        r = take_screenshot(prompt_save=False)
        if r.get("success"):
            return f"Screenshot saved: {r.get('path','?')}"
        return f"Screenshot failed: {r.get('error','unknown')}"
    except Exception as e:
        return f"Screenshot unavailable: {e}"


def _tool_web_search(query: str) -> str:
    """Search the web using Ultron's existing search stack."""
    try:
        # Try Tavily first
        from app import search_web_tavily
        result = search_web_tavily(query, days=3)
        if result.get("sources"):
            snippets = []
            for s in result["sources"][:3]:
                title = s.get("title", "")
                content = s.get("content", "")[:200]
                snippets.append(f"• {title}: {content}")
            return "Search results:\n" + "\n".join(snippets)
    except Exception:
        pass

    try:
        # Fallback to local search
        from local_engine import local_smart_search
        result = local_smart_search(query)
        if result:
            return f"Search result: {str(result)[:400]}"
    except Exception:
        pass

    return "Search unavailable right now."


def _tool_recall_memory(query: str) -> str:
    """Search Ultron's memory for relevant past context."""
    try:
        from memory import recall_relevant, sqlite_get_facts
        results = []

        # Semantic search
        try:
            relevant = recall_relevant(query, top_k=4)
            if relevant:
                for r in relevant[:3]:
                    text = r.get("text") or r.get("content") or str(r)
                    if text and len(text.strip()) > 10:
                        results.append(str(text).strip()[:150])
        except Exception:
            pass

        # Fact search
        try:
            facts = sqlite_get_facts(limit=5)
            for f in facts[:3]:
                fact_str = str(f).strip()
                if query.lower()[:10] in fact_str.lower():
                    results.append(fact_str[:120])
        except Exception:
            pass

        if results:
            return "Memory recall:\n" + "\n".join(f"• {r}" for r in results)
        return "No relevant memories found."
    except Exception:
        return "Memory recall unavailable."


def _tool_calculate(expr: str) -> str:
    """Calculate a mathematical expression."""
    try:
        from action_engine import safe_calculate
        result = safe_calculate(expr)
        if result.get("success"):
            return f"Calculation result: {result['result']}"
        return f"Calculation error: {result.get('error', 'unknown')}"
    except Exception:
        try:
            # Simple fallback
            safe_expr = re.sub(r"[^0-9+\-*/().\s]", "", expr)
            val = eval(safe_expr, {"__builtins__": {}})  # nosec
            return f"Calculation result: {val}"
        except Exception:
            return "Calculation failed."


def _tool_get_weather() -> str:
    """Get current Hyderabad weather."""
    try:
        from action_engine import fetch_weather
        w = fetch_weather()
        if w.get("success"):
            return (
                f"Weather in {w['location']}: {w['description']}, "
                f"{w['temp_c']}°C (feels {w['feels_like']}°C), "
                f"humidity {w['humidity']}%"
            )
        return "Weather unavailable."
    except Exception:
        return "Weather unavailable."


def _tool_check_screen() -> str:
    """See what's currently on Jeevan's screen."""
    try:
        from screen_engine import get_latest_screen_text
        text = get_latest_screen_text()
        if text and len(text.strip()) > 20:
            return f"Screen content: {text.strip()[:300]}"
        return "Screen is empty or unavailable."
    except Exception:
        return "Screen check unavailable."


# =============================================================================
# TOOL CALL PARSER
# =============================================================================
def _parse_tool_call(text: str) -> Optional[Tuple[str, str]]:
    """
    Parse a tool call from LLM text.
    Looks for patterns like:
      <tool name="web_search">query here</tool>
      TOOL_CALL: web_search | query here
      [SEARCH: query here]
    Returns (tool_name, tool_input) or None if no tool call found.
    """
    # Pattern 1: XML-style <tool name="...">...</tool>
    m = re.search(r'<tool\s+name=["\'](\w+)["\']>(.*?)</tool>', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Pattern 2: TOOL_CALL: tool_name | input
    m = re.search(r'TOOL_CALL:\s*(\w+)\s*\|\s*(.+)', text, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Pattern 3: [SEARCH: query]
    m = re.search(r'\[SEARCH:\s*(.+?)\]', text, re.IGNORECASE)
    if m:
        return "web_search", m.group(1).strip()

    # Pattern 4: [RECALL: query]
    m = re.search(r'\[RECALL:\s*(.+?)\]', text, re.IGNORECASE)
    if m:
        return "recall_memory", m.group(1).strip()

    # Pattern 5: NEED_SEARCH: query (in think blocks)
    m = re.search(r'NEED_SEARCH:\s*(.+)', text, re.IGNORECASE)
    if m:
        return "web_search", m.group(1).strip()

    # Pattern 6: NEED_RECALL: query
    m = re.search(r'NEED_RECALL:\s*(.+)', text, re.IGNORECASE)
    if m:
        return "recall_memory", m.group(1).strip()

    return None


def _extract_answer(text: str) -> Optional[str]:
    """Extract final answer from <answer>...</answer> tags."""
    m = re.search(r'<answer>(.*?)</answer>', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _extract_think(text: str) -> Optional[str]:
    """Extract reasoning from <think>...</think> tags."""
    m = re.search(r'<think>(.*?)</think>', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


# =============================================================================
# REASONING SYSTEM PROMPT BUILDER
# =============================================================================
def _build_reasoning_system_prompt(world_state: str, jeevan_profile: str,
                                    complexity: str) -> str:
    """Build the system prompt for the reasoning phase."""
    base = (
        "You are Ultron-J, Jeevan's personal autonomous AI assistant. "
        "You are highly intelligent and reason carefully before answering.\n\n"
    )

    if jeevan_profile:
        base += jeevan_profile + "\n\n"

    if world_state:
        base += world_state + "\n\n"

    if complexity == "COMPLEX":
        base += """REASONING INSTRUCTIONS:
You MUST reason step by step before answering.
Use this exact format:

<think>
1. What is Jeevan actually asking?
2. What do I already know that's relevant?
3. What do I need to find out? (If you need to search/recall, state it here)
4. What's my reasoning and approach?
</think>

TOOLS YOU CAN CALL (one per reasoning step):
Use this format anywhere in your thinking:
  TOOL_CALL: <tool_name> | <input>

Available read-only tools (you may chain them across iterations):
  web_search    | <query>          — cloud search (no browser opens)
  recall_memory | <query>          — search Ultron's stored memory
  calculate     | <expression>     — math, e.g. '23*45 + sqrt(81)'
  get_weather                      — current weather (Hyderabad)
  check_screen                     — read text from the current screen
  file_list     | <path>           — list a directory's contents
  file_read     | <path>           — read up to 5KB of a text file
  get_clipboard                    — read current clipboard text
  get_window                       — active window info
  web_scrape    | <url>            — fetch + extract a page's text
  git_status    | <repo_path>      — git status of a repo
  screenshot                       — save a screenshot silently to disk

Shorthand forms (also accepted):
  NEED_SEARCH: <query>          (same as TOOL_CALL: web_search | …)
  NEED_RECALL: <query>          (same as TOOL_CALL: recall_memory | …)
  [SEARCH: <query>]   [RECALL: <query>]

IMPORTANT — DO NOT request destructive actions through these tools.
For anything that CHANGES Jeevan's machine (delete a file, run a shell
command, send an email, type text, click on screen, write/rename/move
a file, set the clipboard), DO NOT try to do it yourself. State the
proposal in your final <answer> like:
  "I can do X for you — say 'yes' to confirm."
Jeevan's confirmation pipeline will then run it with permission.

Then provide your answer:
<answer>
[Your complete, thoughtful response to Jeevan]
</answer>

IMPORTANT: Do not skip the think block. Jeevan values real reasoning over quick answers."""

    elif complexity == "MEDIUM":
        base += """REASONING INSTRUCTIONS:
Think briefly before answering. Use this format:

<think>
What is being asked? What do I know? What's the best way to answer?
</think>

<answer>
[Your response]
</answer>"""

    return base


# =============================================================================
# MAIN REASONING FUNCTION
# =============================================================================
def reason(
    question: str,
    history: list,
    world_state: str,
    jeevan_profile: str,
    complexity: str = "MEDIUM",
    status_callback=None,
) -> Tuple[str, list]:
    """
    Run the ReAct reasoning loop for a question.

    For COMPLEX queries: up to MAX_ITERATIONS of think→tool→observe.
    For MEDIUM queries: single chain-of-thought pass.

    Args:
        question: The user's question
        history: Recent conversation history (role, content) tuples
        world_state: Built world state string
        jeevan_profile: Jeevan model string
        complexity: SIMPLE / MEDIUM / COMPLEX

    Returns:
        Tuple of:
          - final_answer: The answer to stream to Jeevan (str)
          - reasoning_steps: List of dicts describing what happened (for transparency)
    """
    reasoning_steps = []
    enriched_context = []

    system_prompt = _build_reasoning_system_prompt(world_state, jeevan_profile, complexity)

    # Build initial messages
    messages = [{"role": "system", "content": system_prompt}]

    # Add relevant history (last 6 turns to save tokens)
    for role, content in (history or [])[-6:]:
        messages.append({"role": role, "content": content})

    # Add current question
    messages.append({"role": "user", "content": question})

    if complexity == "SIMPLE":
        # No reasoning loop — direct answer
        return "", reasoning_steps

    # ── REASONING LOOP ────────────────────────────────────────────────────────
    for iteration in range(MAX_ITERATIONS):
        # Add accumulated tool results to the last message if any
        if enriched_context and iteration > 0:
            tool_context = "\n\nTool results so far:\n" + "\n".join(enriched_context)
            # Append to the current question context
            messages[-1]["content"] = question + tool_context

        if status_callback:
            status_callback(f"🧠 Reasoning (step {iteration + 1})...")

        # Batch call to LLM
        response = _call_intelligence_batch(messages)
        if not response:
            break

        reasoning_steps.append({
            "iteration": iteration + 1,
            "raw_response": response[:500],
        })

        # Extract thinking
        think = _extract_think(response)
        if think:
            reasoning_steps[-1]["thinking"] = think[:300]

        # Check for final answer
        answer = _extract_answer(response)
        if answer:
            reasoning_steps[-1]["answer_found"] = True
            return answer, reasoning_steps

        # Check for tool call
        tool_call = _parse_tool_call(response)
        if tool_call:
            tool_name, tool_input = tool_call
            reasoning_steps[-1]["tool_called"] = tool_name
            reasoning_steps[-1]["tool_input"] = tool_input[:100]

            if status_callback:
                status_callback(f"⚙️ Using {tool_name}...")
            # Execute the tool
            tool_result = _execute_tool(tool_name, tool_input)
            reasoning_steps[-1]["tool_result"] = tool_result[:200]

            # Add result to enriched context
            enriched_context.append(f"[{tool_name}({tool_input[:50]})]: {tool_result}")

            # Feed result back into conversation
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": (
                    f"Tool result: {tool_result}\n\n"
                    f"Now continue your reasoning and provide a final answer "
                    f"in <answer>...</answer> tags."
                )
            })
            continue

        # No tool call, no answer tag — the response IS the answer
        # (LLM didn't follow format — use the full response)
        if response and len(response.strip()) > 20:
            # Clean any partial tags
            clean = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
            clean = re.sub(r'</?answer>', '', clean).strip()
            if clean:
                return clean, reasoning_steps
        break

    # If we exhausted iterations without a clean answer, do one final direct call
    final_messages = [
        {
            "role": "system",
            "content": (
                system_prompt +
                "\n\nPrevious reasoning found: " +
                "; ".join(enriched_context[:3]) +
                "\n\nNow give your final answer directly (no XML tags needed)."
            )
        },
        {"role": "user", "content": question}
    ]
    final_response = _call_intelligence_batch(final_messages, max_tokens=1000)

    # Clean any tags from final response
    final_clean = re.sub(r'<think>.*?</think>', '', final_response or "", flags=re.DOTALL)
    final_clean = re.sub(r'</?(?:think|answer)>', '', final_clean).strip()

    return final_clean, reasoning_steps


def get_reasoning_system_for_stream(
    world_state: str,
    jeevan_profile: str,
    enriched_context: str = "",
    complexity: str = "MEDIUM"
) -> str:
    """
    Build the system prompt for the streaming answer phase.
    Called after reasoning is complete — contains all enriched context.
    """
    base = (
        "You are Ultron-J, Jeevan's personal autonomous AI assistant. "
        "You are fiercely intelligent, direct, and deeply helpful. "
        "No hollow phrases. No fluff. Real answers.\n\n"
    )

    if jeevan_profile:
        base += jeevan_profile + "\n\n"

    if world_state:
        base += world_state + "\n\n"

    if enriched_context:
        base += f"RESEARCH CONTEXT (gathered for this response):\n{enriched_context}\n\n"

    if complexity in ("MEDIUM", "COMPLEX"):
        base += (
            "RESPONSE STYLE:\n"
            "• Think through your answer carefully before writing it\n"
            "• Be specific and concrete — Jeevan dislikes vague answers\n"
            "• If something is uncertain, say so honestly\n"
            "• Match depth to complexity — simple questions get simple answers\n"
        )

    return base
