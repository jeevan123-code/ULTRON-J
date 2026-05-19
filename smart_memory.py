"""
smart_memory.py — mem0 wrapper for Ultron-J.
Works alongside memory.py — adds automatic fact extraction from conversations.
Uses local HuggingFace embeddings + local Ollama LLM (mistral) = zero cost, no rate limits.
ChromaDB backend (separate collection "ultron_mem0" from vector_store.py's "ultron_memory").
"""
import os
from typing import List

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from config import CHROMA_DIR
except ImportError:
    CHROMA_DIR = os.path.join(_BASE_DIR, "chroma_memory")

_MEM0_CONFIG = {
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "ultron_mem0",
            "path": CHROMA_DIR,
        }
    },
    "embedder": {
        "provider": "huggingface",
        "config": {
            "model": "multi-qa-MiniLM-L6-cos-v1"
        }
    },
    "llm": {
        "provider": "ollama",
        "config": {
            "model": "tinyllama",
            "ollama_base_url": "http://localhost:11434",
        }
    }
}

_mem0 = None
MEM0_AVAILABLE = False

try:
    from mem0 import Memory as _Mem0Memory
    MEM0_AVAILABLE = True
except ImportError:
    pass


def _get_mem0():
    global _mem0
    if _mem0 is None:
        _mem0 = _Mem0Memory.from_config(_MEM0_CONFIG)
    return _mem0


def remember(text: str, user_id: str = "jeevan") -> dict:
    """Extract and store facts from a conversation turn (background-safe)."""
    if not MEM0_AVAILABLE:
        return {"success": False, "error": "mem0 not installed"}
    try:
        result = _get_mem0().add(text, user_id=user_id)
        return {"success": True, "memories": result}
    except Exception as e:
        print(f"[smart_memory] remember failed: {e}")
        return {"success": False, "error": str(e)}


def recall(query: str, user_id: str = "jeevan", limit: int = 5) -> List[str]:
    """Search mem0 for facts relevant to the query."""
    if not MEM0_AVAILABLE:
        return []
    try:
        # mem0 2.x uses filters= for user_id (not a positional param)
        results = _get_mem0().search(
            query,
            filters={"user_id": user_id},
            limit=limit,
        )
        if isinstance(results, dict):
            items = results.get("results", [])
        else:
            items = results or []
        return [r.get("memory", "") for r in items if r.get("memory")]
    except Exception as e:
        print(f"[smart_memory] recall failed: {e}")
        return []


def get_all_facts(user_id: str = "jeevan") -> List[str]:
    """Return all extracted facts for the user."""
    if not MEM0_AVAILABLE:
        return []
    try:
        results = _get_mem0().get_all(user_id=user_id)
        if isinstance(results, dict):
            items = results.get("results", [])
        else:
            items = results or []
        return [r.get("memory", "") for r in items if r.get("memory")]
    except Exception as e:
        print(f"[smart_memory] get_all_facts failed: {e}")
        return []
