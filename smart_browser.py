"""
smart_browser.py — AI browser agent for Ultron-J.
Replaces fragile Playwright in claude_loop.py with browser-use, which adapts
visually to page changes instead of relying on brittle CSS selectors.
claude_loop.py is kept intact as fallback.
"""
import asyncio
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from browser_use import Agent as BrowserAgent
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False


def _get_llm():
    """Build a LangChain-compatible LLM using Groq (free tier)."""
    try:
        from langchain_groq import ChatGroq
        from config import GROQ_API_KEY, GROQ_MODEL
        llm = ChatGroq(api_key=GROQ_API_KEY, model_name=GROQ_MODEL)
        if not hasattr(llm, "provider"):
            llm.provider = "groq"
        return llm
    except Exception:
        pass
    # Fallback: try Gemini via langchain
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from config import GEMINI_API_KEY
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", google_api_key=GEMINI_API_KEY)
        if not hasattr(llm, "provider"):
            llm.provider = "gemini"
        return llm
    except Exception:
        return None


async def _run_browser_task(task: str, llm=None) -> dict:
    if not BROWSER_USE_AVAILABLE:
        return {"success": False, "error": "browser-use not installed"}
    try:
        if llm is None:
            llm = _get_llm()
        if llm is None:
            return {"success": False, "error": "No LLM available (need GROQ_API_KEY or GEMINI_API_KEY)"}
        agent = BrowserAgent(task=task, llm=llm, use_vision=False, max_failures=3)
        result = await agent.run()
        # AgentHistoryList — get final response text
        final = result.final_result() if hasattr(result, "final_result") else str(result)
        return {"success": True, "result": final or str(result)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def browse(task: str, llm=None) -> dict:
    """Run a browser task synchronously. Returns {success, result/error}."""
    try:
        return asyncio.run(_run_browser_task(task, llm))
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_and_read(query: str) -> dict:
    """Search for a query and return a clear summary."""
    return browse(f"Search for '{query}' and return a clear, concise summary of the results.")
