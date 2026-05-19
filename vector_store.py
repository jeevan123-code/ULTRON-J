"""
vector_store.py — Ultron-J's semantic memory layer.

Fixes the dead-code problem in memory.py:
  - Uses the modern chromadb PersistentClient API (the duckdb+parquet settings
    in memory.py broke on chromadb >=0.4).
  - Falls back to a pure-SQLite + hashing TF-IDF store if chromadb or
    sentence-transformers aren't installed — so "recall" still works on a
    stripped-down machine.
  - Auto-initialises on import so nothing else has to call init().
  - Provides four primitives the rest of Ultron-J uses:
        remember(text, kind, metadata) -> id
        recall(query, n, kind=None)   -> list of {text, score, metadata}
        forget(id)                    -> bool
        stats()                       -> dict

Integration:
  - memory.record_activity() now also calls remember() with kind="activity".
  - memory.store_conversation() calls remember() with kind="turn".
  - intelligence_core.think_and_stream() calls recall() BEFORE the LLM
    thinks, so every question starts with "have I done this before?".
  - research_engine caches its findings here with kind="research".
  - memory_distiller stores lessons here with kind="lesson".

The kinds let us query one slice of memory without mixing research with
trivial chat. recall(query, kind="lesson") gets distilled wisdom;
recall(query, kind="research") gets prior research; recall(query) gets
everything.
"""

import json
import os
import re
import time
import hashlib
import sqlite3
import threading
import datetime
import uuid
from typing import List, Dict, Optional

try:
    from config import CHROMA_DIR, _BASE_DIR
except ImportError:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CHROMA_DIR = os.path.join(_BASE_DIR, "chroma_memory")

# =============================================================================
# BACKEND DETECTION — prefer chromadb+sentence-transformers, fall back to BM25
# =============================================================================

_BACKEND = "none"
_chroma_client = None
_chroma_collection = None
_embed_model = None

try:
    import chromadb
    try:
        from sentence_transformers import SentenceTransformer
        _ST_AVAILABLE = True
    except ImportError:
        _ST_AVAILABLE = False
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False
    _ST_AVAILABLE = False


# Fallback store file (used when chromadb isn't available)
_FALLBACK_DB = os.path.join(os.path.dirname(CHROMA_DIR), "vector_store_fallback.db")

_init_lock = threading.Lock()
_initialised = False

# Query-embedding LRU cache — SentenceTransformer.encode() is the dominant
# cost on the /ask hot path (200-500ms per call on CPU). intelligence_core
# calls recall() 3+ times per request with the same query, each previously
# re-encoding from scratch. Caching here means one encode per query instead
# of one encode per recall.
_EMB_CACHE_MAX = 128
_EMB_CACHE_TTL = 60.0   # seconds — short enough that stale models don't haunt us
_emb_cache: Dict[str, tuple] = {}    # query -> (embedding, ts)
_emb_cache_lock = threading.Lock()


def _embed(query: str):
    """Cached SentenceTransformer encode. Falls back to live encode on miss."""
    if _embed_model is None:
        return None
    key = query.strip()
    if not key:
        return None
    now = time.time()
    with _emb_cache_lock:
        hit = _emb_cache.get(key)
        if hit is not None and (now - hit[1]) < _EMB_CACHE_TTL:
            return hit[0]
    emb = _embed_model.encode([key]).tolist()[0]
    with _emb_cache_lock:
        if len(_emb_cache) >= _EMB_CACHE_MAX:
            try:
                _emb_cache.pop(next(iter(_emb_cache)))
            except StopIteration:
                pass
        _emb_cache[key] = (emb, now)
    return emb


def _init():
    """Idempotent, thread-safe initialisation. Picks the best available backend."""
    global _BACKEND, _chroma_client, _chroma_collection, _embed_model, _initialised
    with _init_lock:
        if _initialised:
            return
        _initialised = True

        if _CHROMA_AVAILABLE and _ST_AVAILABLE:
            try:
                os.makedirs(CHROMA_DIR, exist_ok=True)
                # Modern chromadb API — PersistentClient replaces the old Settings(chroma_db_impl="duckdb+parquet") pattern
                _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
                _chroma_collection = _chroma_client.get_or_create_collection(
                    "ultron_memory",
                    metadata={"hnsw:space": "cosine"},
                )
                # Small model (~90MB) — good enough for personal recall
                _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
                _BACKEND = "chroma"
                print("[vector_store] Backend: chromadb + sentence-transformers (ready).")
                return
            except Exception as e:
                print(f"[vector_store] chromadb failed to initialise: {e}")
                _chroma_client = None
                _chroma_collection = None
                _embed_model = None

        # Fallback: pure-SQLite BM25-style keyword store
        _init_fallback_db()
        _BACKEND = "sqlite_bm25"
        print("[vector_store] Backend: SQLite keyword fallback (chromadb unavailable).")


def _init_fallback_db():
    """Create the fallback SQLite store with FTS5 if available, else regular table."""
    conn = sqlite3.connect(_FALLBACK_DB, check_same_thread=False)
    try:
        # Try FTS5 (built in to most modern SQLite) — if it fails, fall back to LIKE
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories
                USING fts5(id UNINDEXED, text, kind UNINDEXED, metadata UNINDEXED, ts UNINDEXED)
            """)
        except sqlite3.OperationalError:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    text TEXT,
                    kind TEXT,
                    metadata TEXT,
                    ts TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_kind ON memories(kind)")
        conn.commit()
    finally:
        conn.close()


def _fallback_has_fts():
    conn = sqlite3.connect(_FALLBACK_DB, check_same_thread=False)
    try:
        cur = conn.execute("SELECT sql FROM sqlite_master WHERE name='memories'")
        row = cur.fetchone()
        return bool(row and "fts5" in (row[0] or "").lower())
    finally:
        conn.close()


# Auto-initialise on import so callers don't have to remember
_init()


# =============================================================================
# PUBLIC API
# =============================================================================

def remember(
    text: str,
    kind: str = "general",
    metadata: Optional[Dict] = None,
) -> Optional[str]:
    """Store a piece of text. Returns its id, or None on failure.

    kind options used in Ultron-J:
      - "turn"     conversation turns
      - "activity" record_activity calls (short)
      - "research" research_engine findings
      - "lesson"   memory_distiller distillations
      - "skill"    skill_learner acquisitions
      - "episode"  rich episodic events
      - "concept"  concept entries
    """
    if not text or not text.strip():
        return None
    text = text.strip()[:8000]  # hard cap — nothing useful beyond this

    doc_id = str(uuid.uuid4())
    meta = dict(metadata or {})
    meta.setdefault("ts", datetime.datetime.now().isoformat())
    meta["kind"] = kind

    if _BACKEND == "chroma":
        try:
            emb = _embed_model.encode([text]).tolist()[0]
            # chromadb metadata must be JSON-scalars only
            flat_meta = {k: (v if isinstance(v, (str, int, float, bool)) else json.dumps(v))
                         for k, v in meta.items()}
            _chroma_collection.add(
                embeddings=[emb],
                documents=[text],
                ids=[doc_id],
                metadatas=[flat_meta],
            )
            return doc_id
        except Exception as e:
            print(f"[vector_store] remember (chroma) failed: {e}")
            return None

    if _BACKEND == "sqlite_bm25":
        try:
            conn = sqlite3.connect(_FALLBACK_DB, check_same_thread=False)
            try:
                conn.execute(
                    "INSERT INTO memories (id, text, kind, metadata, ts) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, text, kind, json.dumps(meta), meta["ts"]),
                )
                conn.commit()
            finally:
                conn.close()
            return doc_id
        except Exception as e:
            print(f"[vector_store] remember (sqlite) failed: {e}")
            return None

    return None


def recall(
    query: str,
    n: int = 5,
    kind: Optional[str] = None,
    min_score: float = 0.0,
) -> List[Dict]:
    """Semantic search. Returns [{text, score, metadata, id}, ...].

    score is similarity (0..1 for chroma, 0..1 normalised for fallback).
    kind filters by memory type; pass None to search everything.
    """
    if not query or not query.strip():
        return []

    if _BACKEND == "chroma":
        try:
            emb = _embed(query)
            if emb is None:
                return []
            # ChromaDB 1.x where-filter is broken with HNSW — fetch without filter,
            # then filter by kind in Python. Fetch extra results to compensate.
            try:
                total = _chroma_collection.count()
            except Exception:
                total = n
            if total == 0:
                return []
            fetch_n = min(max(n * 4 if kind else n, 1), total)
            res = _chroma_collection.query(
                query_embeddings=[emb],
                n_results=fetch_n,
            )
            docs  = res.get("documents", [[]])[0]
            ids   = res.get("ids",        [[]])[0]
            metas = res.get("metadatas",  [[]])[0]
            dists = res.get("distances",  [[]])[0]
            out = []
            for doc, did, meta, dist in zip(docs, ids, metas, dists):
                m = meta or {}
                if kind and m.get("kind") != kind:
                    continue
                score = max(0.0, 1.0 - float(dist))
                if score < min_score:
                    continue
                out.append({"id": did, "text": doc, "score": score, "metadata": m})
                if len(out) >= n:
                    break
            return out
        except Exception as e:
            print(f"[vector_store] recall (chroma) failed: {e}")
            return []

    if _BACKEND == "sqlite_bm25":
        return _fallback_recall(query, n, kind, min_score)

    return []


def _fallback_recall(query: str, n: int, kind: Optional[str], min_score: float) -> List[Dict]:
    """Keyword / FTS5 search fallback."""
    results = []
    has_fts = _fallback_has_fts()
    conn = sqlite3.connect(_FALLBACK_DB, check_same_thread=False)
    try:
        if has_fts:
            # FTS5 MATCH — sanitise query to avoid syntax errors
            safe = re.sub(r'[^\w\s]', ' ', query).strip()
            if not safe:
                return []
            # Treat every token as optional (OR)
            tokens = [t for t in safe.split() if len(t) > 1]
            if not tokens:
                return []
            match = " OR ".join(tokens)
            try:
                if kind:
                    cur = conn.execute(
                        "SELECT id, text, kind, metadata, ts, rank FROM memories "
                        "WHERE memories MATCH ? AND kind = ? ORDER BY rank LIMIT ?",
                        (match, kind, n * 3),
                    )
                else:
                    cur = conn.execute(
                        "SELECT id, text, kind, metadata, ts, rank FROM memories "
                        "WHERE memories MATCH ? ORDER BY rank LIMIT ?",
                        (match, n * 3),
                    )
                rows = cur.fetchall()
                # FTS5 rank is negative and unbounded; normalise with a sigmoid-ish transform
                for row in rows:
                    did, text, k, meta_json, ts, rank = row
                    try:
                        meta = json.loads(meta_json) if meta_json else {}
                    except Exception:
                        meta = {}
                    # BM25 rank is more-negative = better
                    score = 1.0 / (1.0 + abs(float(rank or 0)))
                    if score < min_score:
                        continue
                    results.append({"id": did, "text": text, "score": score, "metadata": meta})
                results.sort(key=lambda r: r["score"], reverse=True)
                return results[:n]
            except sqlite3.OperationalError:
                pass  # fall through to LIKE below

        # No FTS5 → fall back to LIKE scoring
        tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
        if not tokens:
            return []
        where = "1=1"
        params: list = []
        if kind:
            where = "kind = ?"
            params.append(kind)
        cur = conn.execute(
            f"SELECT id, text, kind, metadata, ts FROM memories WHERE {where} "
            f"ORDER BY ts DESC LIMIT 1000",
            params,
        )
        rows = cur.fetchall()
        for row in rows:
            did, text, k, meta_json, ts = row
            tl = (text or "").lower()
            hits = sum(1 for t in tokens if t in tl)
            if hits == 0:
                continue
            score = hits / len(tokens)
            if score < min_score:
                continue
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except Exception:
                meta = {}
            results.append({"id": did, "text": text, "score": score, "metadata": meta})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:n]
    finally:
        conn.close()


def forget(doc_id: str) -> bool:
    """Delete a memory by id."""
    if _BACKEND == "chroma":
        try:
            _chroma_collection.delete(ids=[doc_id])
            return True
        except Exception:
            return False
    if _BACKEND == "sqlite_bm25":
        try:
            conn = sqlite3.connect(_FALLBACK_DB, check_same_thread=False)
            try:
                conn.execute("DELETE FROM memories WHERE id = ?", (doc_id,))
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception:
            return False
    return False


def stats() -> Dict:
    """Return store status for the /status endpoint."""
    info = {"backend": _BACKEND, "ready": _BACKEND != "none"}
    if _BACKEND == "chroma":
        try:
            info["count"] = _chroma_collection.count()
        except Exception:
            info["count"] = -1
    elif _BACKEND == "sqlite_bm25":
        try:
            conn = sqlite3.connect(_FALLBACK_DB, check_same_thread=False)
            cur = conn.execute("SELECT COUNT(*), kind FROM memories GROUP BY kind")
            by_kind = {k: c for c, k in cur.fetchall()}
            total = sum(by_kind.values())
            conn.close()
            info["count"] = total
            info["by_kind"] = by_kind
        except Exception:
            info["count"] = -1
    return info


def recall_formatted_for_prompt(query: str, n: int = 3, kind: Optional[str] = None) -> str:
    """Recall and format results as a string ready for LLM prompt injection.

    Empty string if nothing relevant. Used by intelligence_core before thinking.
    """
    hits = recall(query, n=n, kind=kind, min_score=0.35)
    if not hits:
        return ""
    lines = ["=== Relevant Past Context ==="]
    for i, h in enumerate(hits, 1):
        text = h["text"][:300]
        meta = h.get("metadata", {})
        ts = meta.get("ts", "")[:10] if meta.get("ts") else ""
        k = meta.get("kind", "")
        tag = f"[{k}, {ts}]" if k and ts else (f"[{k}]" if k else "")
        lines.append(f"{i}. {tag} {text}")
    return "\n".join(lines)


# =============================================================================
# CONVENIENCE HELPERS — short-circuit for frequently-stored types
# =============================================================================

def remember_turn(role: str, message: str, session_id: str = "default") -> Optional[str]:
    """Convenience wrapper called by memory.store_conversation."""
    return remember(
        f"{role}: {message}",
        kind="turn",
        metadata={"role": role, "session": session_id},
    )


def remember_research(query: str, summary: str, sources: List[str]) -> Optional[str]:
    """Store a research finding so we don't re-research it later."""
    text = f"Query: {query}\n\nFindings:\n{summary}"
    return remember(text, kind="research", metadata={"query": query, "sources": sources[:10]})


def remember_lesson(lesson: str, source: str = "reflection") -> Optional[str]:
    return remember(lesson, kind="lesson", metadata={"source": source})


def find_prior_research(query: str, n: int = 2) -> List[Dict]:
    """Called by research_engine to skip work that's already been done."""
    return recall(query, n=n, kind="research", min_score=0.55)


# =============================================================================
# SMOKE TEST
# =============================================================================
if __name__ == "__main__":
    print("== vector_store smoke test ==")
    print(f"stats (before): {stats()}")
    i1 = remember("Jeevan is building Ultron-J, a self-hosted Flask AI assistant.", kind="fact")
    i2 = remember("Groq is the fastest free LLM provider available.", kind="fact")
    i3 = remember("How do I make my search engine better?", kind="turn")
    print(f"stored 3 ids: {i1}, {i2}, {i3}")
    print(f"stats (after): {stats()}")
    print("\nrecall 'ultron self-hosted':")
    for r in recall("ultron self-hosted", n=3):
        print(f"  [{r['score']:.3f}] {r['text'][:80]}")
    print("\nrecall 'search engine' kind=turn:")
    for r in recall("search engine", n=3, kind="turn"):
        print(f"  [{r['score']:.3f}] {r['text'][:80]}")
