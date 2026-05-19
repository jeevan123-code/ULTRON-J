"""
code_index.py — Semantic codebase indexer for Ultron-J.

What this does:
  - Walks every .py file in the project
  - Extracts every function and class using ast (real parse, not regex)
  - Stores chunks in a local SQLite database with full-text search
  - Tracks file mtimes — only re-indexes files that actually changed
  - Provides search_code(query) and get_code_context(question)
  - Also stores into vector_store (ChromaDB) for semantic recall if available
  - Auto-refreshes in a background thread every 5 minutes

No hardcoding. No fake results. If a file can't be parsed, it's skipped silently.
"""

import ast
import json
import os
import re
import sqlite3
import threading
import time
import datetime
from typing import List, Dict, Optional

_BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
_DB_PATH    = os.path.join(_BASE_DIR, "code_index.db")
_STATE_FILE = os.path.join(_BASE_DIR, "code_index_state.json")

_lock         = threading.Lock()
_indexed_once = False

# Directories to skip when walking the project
_SKIP_DIRS = {
    ".venv", "venv", "__pycache__", "site-packages", ".git",
    "_upgrade_workspace", "self_modify_backups", "self_upgrade_backups",
    "self_upgrade_backups", "visual_verify_cache", "browser_cache",
    "chroma_store", "chroma_memory",
}

# Keywords that signal the user is asking about code
_CODE_KEYWORDS = {
    "function", "route", "class", "module", "import", "def ",
    "error in", "bug in", "why does", "how does", "what does",
    "where is", "which file", "which function", "traceback",
    "exception", "undefined", "not found", "broken", "fails",
    "intent", "router", "engine", "handler", "endpoint", "action",
    "fix the", "change the", "update the", "in app.py", "in llm",
}


# =============================================================================
# DATABASE
# =============================================================================

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT NOT NULL,
                file      TEXT NOT NULL,
                line      INTEGER NOT NULL,
                kind      TEXT NOT NULL,
                source    TEXT NOT NULL,
                docstring TEXT DEFAULT '',
                indexed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file);
            CREATE INDEX IF NOT EXISTS idx_chunks_name ON chunks(name);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(name, file, source, docstring,
                           content='chunks', content_rowid='id');
        """)
        conn.commit()


def _clear_file_chunks(conn: sqlite3.Connection, rel_path: str):
    """Delete all chunks from a specific file before re-indexing it."""
    conn.execute("DELETE FROM chunks WHERE file = ?", (rel_path,))
    conn.execute("DELETE FROM chunks_fts WHERE file = ?", (rel_path,))
    conn.commit()


def _insert_chunks(conn: sqlite3.Connection, chunks: List[Dict]):
    now = datetime.datetime.now().isoformat()
    for ch in chunks:
        cur = conn.execute(
            "INSERT INTO chunks (name, file, line, kind, source, docstring, indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ch["name"], ch["file"], ch["line"], ch["kind"],
             ch["source"], ch.get("docstring", ""), now),
        )
        rowid = cur.lastrowid
        conn.execute(
            "INSERT INTO chunks_fts (rowid, name, file, source, docstring) "
            "VALUES (?, ?, ?, ?, ?)",
            (rowid, ch["name"], ch["file"], ch["source"], ch.get("docstring", "")),
        )
    conn.commit()


# =============================================================================
# FILE PARSING
# =============================================================================

def _get_py_files() -> List[str]:
    files = []
    for root, dirs, filenames in os.walk(_BASE_DIR):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(os.path.join(root, fn))
    return files


def _extract_chunks(filepath: str) -> List[Dict]:
    """Parse a .py file and return list of chunk dicts for every top-level
    function, class, and method. Uses ast — real parse, not regex."""
    try:
        source = open(filepath, encoding="utf-8", errors="replace").read()
        tree   = ast.parse(source, filename=filepath)
    except Exception:
        return []

    rel_path = os.path.relpath(filepath, _BASE_DIR).replace("\\", "/")
    chunks   = []

    def _process(node, parent_name: str = ""):
        kind    = "class" if isinstance(node, ast.ClassDef) else "function"
        full_name = f"{parent_name}.{node.name}" if parent_name else node.name

        try:
            seg = ast.get_source_segment(source, node) or ""
        except Exception:
            seg = ""

        docstring = ast.get_docstring(node) or ""

        # Build a readable chunk: header + docstring (if any) + first 600 chars of source
        header = f"[{kind}] {rel_path}:{node.lineno} — {full_name}"
        body   = seg[:700] if seg else f"(source unavailable)"
        text   = f"{header}\n{body}"

        chunks.append({
            "name":      full_name,
            "file":      rel_path,
            "line":      node.lineno,
            "kind":      kind,
            "source":    text,
            "docstring": docstring[:300],
        })

        # If this is a class, also index its methods
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _process(child, parent_name=node.name)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _process(node)

    # Also extract Flask route definitions (decorated functions)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                # Look for @app.route('/...') or @bp.route('/...')
                deco_src = ast.get_source_segment(source, deco) or ""
                if ".route(" in deco_src or "route(" in deco_src:
                    seg = ast.get_source_segment(source, node) or ""
                    text = (
                        f"[route] {rel_path}:{node.lineno} — {node.name}\n"
                        f"Decorator: {deco_src[:120]}\n"
                        f"{seg[:500]}"
                    )
                    chunks.append({
                        "name":      f"route:{node.name}",
                        "file":      rel_path,
                        "line":      node.lineno,
                        "kind":      "route",
                        "source":    text,
                        "docstring": ast.get_docstring(node) or "",
                    })

    return chunks


# =============================================================================
# MTIME STATE
# =============================================================================

def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            return json.load(open(_STATE_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    try:
        from memory import atomic_json_write
        atomic_json_write(_STATE_FILE, state)
    except Exception:
        try:
            tmp = _STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f)
            os.replace(tmp, _STATE_FILE)
        except Exception:
            pass


def _needs_reindex(filepath: str, state: dict) -> bool:
    try:
        mtime = os.path.getmtime(filepath)
        return state.get(filepath) != mtime
    except Exception:
        return True


# =============================================================================
# INDEXING
# =============================================================================

def build_code_index(force: bool = False):
    """Index all changed .py files. Idempotent — safe to call repeatedly."""
    global _indexed_once

    _init_db()
    state    = _load_state()
    py_files = _get_py_files()
    new_state = dict(state)

    indexed_files  = 0
    indexed_chunks = 0

    with _get_conn() as conn:
        for filepath in py_files:
            if not force and not _needs_reindex(filepath, state):
                continue

            chunks = _extract_chunks(filepath)
            if not chunks:
                try:
                    new_state[filepath] = os.path.getmtime(filepath)
                except Exception:
                    pass
                continue

            rel_path = os.path.relpath(filepath, _BASE_DIR).replace("\\", "/")
            _clear_file_chunks(conn, rel_path)
            _insert_chunks(conn, chunks)

            try:
                new_state[filepath] = os.path.getmtime(filepath)
            except Exception:
                pass

            indexed_files  += 1
            indexed_chunks += len(chunks)

            # Mirror to vector_store (semantic search) if available
            try:
                import vector_store as _vs
                for ch in chunks:
                    _vs.remember(ch["source"], kind="code", metadata={
                        "file": ch["file"], "name": ch["name"],
                        "line": ch["line"], "chunk_kind": ch["kind"],
                    })
            except Exception:
                pass

    _save_state(new_state)

    with _lock:
        _indexed_once = True

    if indexed_files > 0:
        print(f"[+] Code index: {indexed_chunks} chunks from {indexed_files} files "
              f"(total files: {len(py_files)})")


def start_code_indexer():
    """Start background indexer. Initial index runs immediately, then every 5 min."""
    def _run():
        build_code_index()
        while True:
            time.sleep(300)
            try:
                build_code_index()
            except Exception:
                pass

    t = threading.Thread(target=_run, daemon=True, name="code-indexer")
    t.start()
    return t


# =============================================================================
# SEARCH
# =============================================================================

def search_code(query: str, n: int = 6) -> List[Dict]:
    """
    Search the code index for relevant chunks.

    Strategy:
      1. Exact name match (score=1.0)       — "detect_intent" → finds it instantly
      2. Semantic search via ChromaDB (real scores 0.45-0.9) — natural language
      3. FTS5 keyword match (score=0.5)     — exact keyword fallback
      4. LIKE partial match (score=0.3)     — last resort

    Semantic runs before FTS so natural-language queries get meaningful results.
    """
    if not query or not query.strip():
        return []

    _init_db()
    results  = []
    seen_key = set()   # (name, file) dedup

    query_clean = query.strip()
    words = re.findall(r"\w+", query_clean.lower())

    # 1. Exact name match — always check first
    with _get_conn() as conn:
        try:
            rows = conn.execute(
                "SELECT id, name, file, line, kind, source FROM chunks "
                "WHERE lower(name) = ? LIMIT ?",
                (query_clean.lower(), n),
            ).fetchall()
            for row in rows:
                key = (row["name"], row["file"])
                if key not in seen_key:
                    results.append({**dict(row), "score": 1.0})
                    seen_key.add(key)
        except Exception:
            pass

    if len(results) >= n:
        return results[:n]

    # 2. Semantic search via ChromaDB (natural language understanding)
    try:
        import vector_store as _vs
        if _vs._BACKEND == "chroma":
            sem_hits = _vs.recall(query_clean, n=n * 2, kind="code", min_score=0.40)
            for hit in sem_hits:
                meta = hit.get("metadata", {})
                name = meta.get("name", "")
                file = meta.get("file", "")
                key  = (name, file)
                if key not in seen_key and len(results) < n:
                    results.append({
                        "id":     None,
                        "name":   name,
                        "file":   file,
                        "line":   int(meta.get("line", 0)),
                        "kind":   meta.get("chunk_kind", "function"),
                        "source": hit.get("text", ""),
                        "score":  round(hit["score"], 3),
                    })
                    seen_key.add(key)
    except Exception:
        pass

    if len(results) >= n:
        return results[:n]

    # 3. FTS5 keyword match — for cases where semantic doesn't help
    with _get_conn() as conn:
        try:
            fts_query = " OR ".join(f'"{w}"' for w in words if len(w) > 2)
            if fts_query:
                rows = conn.execute(
                    "SELECT c.id, c.name, c.file, c.line, c.kind, c.source "
                    "FROM chunks_fts f JOIN chunks c ON c.id = f.rowid "
                    "WHERE chunks_fts MATCH ? LIMIT ?",
                    (fts_query, n * 3),
                ).fetchall()
                for row in rows:
                    key = (row["name"], row["file"])
                    if key not in seen_key and len(results) < n:
                        results.append({**dict(row), "score": 0.5})
                        seen_key.add(key)
        except Exception:
            pass

    if len(results) >= n:
        return results[:n]

    # 4. LIKE fallback
    with _get_conn() as conn:
        try:
            for word in words:
                if len(word) < 3:
                    continue
                rows = conn.execute(
                    "SELECT id, name, file, line, kind, source FROM chunks "
                    "WHERE lower(name) LIKE ? OR lower(source) LIKE ? LIMIT ?",
                    (f"%{word}%", f"%{word}%", n),
                ).fetchall()
                for row in rows:
                    key = (row["name"], row["file"])
                    if key not in seen_key and len(results) < n:
                        results.append({**dict(row), "score": 0.3})
                        seen_key.add(key)
                if len(results) >= n:
                    break
        except Exception:
            pass

    return results[:n]


def get_code_context(question: str, max_chars: int = 1800) -> str:
    """
    Return relevant code context for a coding-related question.
    Returns empty string if the question is not code-related.
    """
    q_lower = question.lower()
    if not any(kw in q_lower for kw in _CODE_KEYWORDS):
        return ""

    hits = search_code(question, n=4)
    if not hits:
        return ""

    parts = []
    total = 0
    for hit in hits:
        chunk = hit.get("source", "")
        if not chunk:
            continue
        if total + len(chunk) > max_chars:
            chunk = chunk[:max_chars - total]
        if chunk:
            parts.append(chunk)
            total += len(chunk)
        if total >= max_chars:
            break

    if not parts:
        return ""
    return "=== Relevant Code ===\n" + "\n---\n".join(parts)


def get_file_summary(filepath: str) -> str:
    """Return a list of all functions/classes in a file. Useful for 'what's in app.py?'"""
    rel_path = os.path.relpath(
        os.path.join(_BASE_DIR, filepath), _BASE_DIR
    ).replace("\\", "/")
    _init_db()
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT name, line, kind FROM chunks WHERE file = ? ORDER BY line",
                (rel_path,),
            ).fetchall()
        if not rows:
            return f"No index entry for {filepath}. Run build_code_index() first."
        lines = [f"  [{r['kind']}] {r['name']} (line {r['line']})" for r in rows]
        return f"**{filepath}** — {len(rows)} indexed items:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error reading code index: {e}"


def stats() -> dict:
    """Return index statistics."""
    _init_db()
    try:
        with _get_conn() as conn:
            total  = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            files  = conn.execute("SELECT COUNT(DISTINCT file) FROM chunks").fetchone()[0]
            routes = conn.execute("SELECT COUNT(*) FROM chunks WHERE kind='route'").fetchone()[0]
            funcs  = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE kind='function'"
            ).fetchone()[0]
            classes = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE kind='class'"
            ).fetchone()[0]
        return {
            "total_chunks": total, "files_indexed": files,
            "routes": routes, "functions": funcs, "classes": classes,
        }
    except Exception as e:
        return {"error": str(e)}
