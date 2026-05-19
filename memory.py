"""
memory.py — Everything related to storing and retrieving memory for Ultron-J ULTIMATE.

Five layers (up from four):
1. JSON memory (memory.json)          — long-term facts + conversation log
2. SQLite (ultron.db)                 — per-session history + patterns + episodes table
3. ChromaDB (chroma_memory/)          — semantic vector search (optional)
4. Pattern memory (patterns.json)     — behavior, work rhythms, activity tracking
5. Episodic memory (episodic_memory.json) — NEW: rich event memories with emotional context

NEW in ULTIMATE:
- Episodic memory: remembers specific events (what happened, when, emotional valence)
- Memory consolidation: auto-compress old episodes into summaries
- Entity graph: tracks people, projects, topics Jeevan mentions with relationships
- Fuzzy search: search across all memory layers simultaneously
- Memory decay: old low-importance memories fade over time
- Stale project detection: notices when Jeevan abandons a project
- Entity timeline: track what Jeevan worked on and when
"""

import json
import os
import sqlite3
import threading
import datetime
import uuid
import tempfile
import shutil
import time
from config import (
    MEMORY_FILE, SELF_IMPROVE_FILE, CHROMA_DIR,
    DB_FILE, MAX_CONVERSATIONS, MAX_FACTS, MAX_IMPROVEMENTS,
    SEMANTIC_TOP_K, PATTERNS_FILE, BRIEFING_FILE,
    EPISODE_FILE, ENTITY_GRAPH_FILE, MAX_EPISODES,
    CONSOLIDATION_THRESHOLD, MIN_EPISODES_TO_CONSOLIDATE,
    HISTORY_FETCH_LIMIT,
)

# ── Optional heavy deps ───────────────────────────────────────────────────────
# NOTE: The old chromadb integration in this file is now routed through
# vector_store.py which uses the modern chromadb PersistentClient API and
# falls back to SQLite FTS5 when chromadb / sentence-transformers are absent.
try:
    import vector_store as _vstore
    SEMANTIC_MEMORY_AVAILABLE = (_vstore.stats().get("backend") != "none")
    _VSTORE_OK = True
except Exception:
    SEMANTIC_MEMORY_AVAILABLE = False
    _VSTORE_OK = False
    _vstore = None

def atomic_json_write(filepath: str, data) -> None:
    """Write JSON atomically: tmp file -> fsync -> rename, with Windows
    OneDrive-aware retries.

    On Windows + OneDrive the destination is briefly held open by the
    sync agent (and AV scanners), making ``os.replace`` fail with
    ``PermissionError: [WinError 5]`` — the same error filling the
    heartbeat log here and causing 500s under L3 concurrency. Retry the
    rename with short exponential backoff so a momentary lock doesn't
    drop the write. If every retry loses the race, fall back to a plain
    ``shutil.copyfile`` so the newest data still lands (non-atomic, but
    better than losing the write entirely)."""
    dirpath = os.path.dirname(os.path.abspath(filepath)) or "."
    os.makedirs(dirpath, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".tmp_", suffix=".json", dir=dirpath
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        last_err = None
        for attempt in range(6):
            try:
                os.replace(tmp_path, filepath)
                return
            except PermissionError as e:
                last_err = e
                time.sleep(0.05 * (2 ** attempt))   # 50, 100, 200, 400, 800, 1600 ms

        # All retries lost the race — degrade to non-atomic copy so the
        # newest data still lands instead of being dropped.
        try:
            shutil.copyfile(tmp_path, filepath)
            return
        except Exception:
            raise last_err
    except Exception:
        raise
    finally:
        # tmp_path is gone once os.replace succeeded; otherwise clean it up.
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass

# =============================================================================
# SQLITE — thread-safe WAL
# =============================================================================

def _db_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=2)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _db_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role       TEXT,
            message    TEXT,
            timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            fact       TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type  TEXT,
            event_data  TEXT,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # NEW: episodes table for richer episodic memory
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id  TEXT UNIQUE,
            kind        TEXT,
            summary     TEXT,
            detail      TEXT,
            entities    TEXT,
            valence     REAL DEFAULT 0.0,
            importance  REAL DEFAULT 0.5,
            session_id  TEXT,
            recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()


def sqlite_save_message(session_id: str, role: str, message: str):
    conn = _db_conn()
    try:
        conn.execute(
            "INSERT INTO conversations (session_id, role, message) VALUES (?, ?, ?)",
            (session_id, role, message),
        )
        conn.commit()
    finally:
        conn.close()


def sqlite_get_history(session_id: str) -> list:
    conn = _db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT role, message FROM conversations "
            "WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, HISTORY_FETCH_LIMIT),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    rows.reverse()
    return rows


def sqlite_save_fact(session_id: str, fact: str):
    conn = _db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM facts WHERE session_id=? AND fact=?",
            (session_id, fact),
        )
        if not cur.fetchone():
            conn.execute(
                "INSERT INTO facts (session_id, fact) VALUES (?, ?)",
                (session_id, fact),
            )
            conn.commit()
    finally:
        conn.close()


def sqlite_get_facts(session_id: str) -> list:
    conn = _db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT fact FROM facts WHERE session_id=?", (session_id,))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def sqlite_get_session_stats(session_id: str) -> int:
    conn = _db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM conversations WHERE session_id=?",
            (session_id,),
        )
        count = cur.fetchone()[0]
    finally:
        conn.close()
    return count


def clean_fact(text: str) -> str:
    text = text.lower().strip()
    for p in ["i like", "i love", "i enjoy", "my favorite is",
              "i prefer", "i am", "my name is"]:
        if text.startswith(p):
            return text.replace(p, "", 1).strip()
    return text

# =============================================================================
# LAYER 1 — JSON MEMORY
# =============================================================================

_json_lock = threading.Lock()


def load_memory() -> dict:
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "conversations": [],
        "facts_about_jeevan": [],
        "session_summaries": [],
        "stale_projects": [],
    }


def save_memory(data: dict):
    with _json_lock:
        atomic_json_write(MEMORY_FILE, data)


def store_conversation(role: str, message: str, session_id: str = "default"):
    data = load_memory()
    data.setdefault("conversations", []).append({
        "role":     role,
        "message":  message[:2000],
        "session":  session_id,
        "at":       datetime.datetime.now().isoformat(),
    })
    if len(data["conversations"]) > MAX_CONVERSATIONS:
        data["conversations"] = data["conversations"][-MAX_CONVERSATIONS:]
    save_memory(data)

    # Also remember the turn in the semantic layer for later recall.
    # User turns are more valuable for recall than assistant turns.
    if _VSTORE_OK and message and len(message.strip()) > 10:
        try:
            _vstore.remember_turn(role, message[:2000], session_id=session_id)
        except Exception:
            pass


def store_fact(fact: str):
    fact = clean_fact(fact)
    if not fact:
        return
    data = load_memory()
    facts = data.setdefault("facts_about_jeevan", [])
    if fact not in facts:
        facts.append(fact)
    if len(facts) > MAX_FACTS:
        data["facts_about_jeevan"] = facts[-MAX_FACTS:]
    save_memory(data)


def recall_relevant(query: str, n: int = 5) -> list:
    """Simple keyword recall from JSON facts."""
    data  = load_memory()
    facts = data.get("facts_about_jeevan", [])
    q     = query.lower()
    scored = [(f, sum(1 for w in q.split() if w in f.lower())) for f in facts]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [f for f, score in scored[:n] if score > 0]


def load_improvements() -> list:
    if os.path.exists(SELF_IMPROVE_FILE):
        try:
            with open(SELF_IMPROVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_improvements(improvements: list):
    with _json_lock:
        atomic_json_write(SELF_IMPROVE_FILE, improvements[-MAX_IMPROVEMENTS:])


def migrate_existing_memory():
    """One-time migration: ensure memory file has all required keys."""
    data = load_memory()
    changed = False
    for key in ["conversations", "facts_about_jeevan", "session_summaries", "stale_projects"]:
        if key not in data:
            data[key] = []
            changed = True
    if changed:
        save_memory(data)

# =============================================================================
# LAYER 4 — PATTERN MEMORY
# =============================================================================

_pattern_lock = threading.Lock()


def load_patterns() -> dict:
    if os.path.exists(PATTERNS_FILE):
        try:
            with open(PATTERNS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active_hours": {},
        "active_days":  {},
        "topics":       {},
        "modes":        {"cloud": 0, "local": 0},
        "streak_days":  [],
        "projects":     {},
        "last_active":  None,
    }


def save_patterns(data: dict):
    with _pattern_lock:
        atomic_json_write(PATTERNS_FILE, data)


def record_activity(topic: str = "", mode: str = "", session_id: str = ""):
    """Record an activity event for pattern learning."""
    data  = load_patterns()
    now   = datetime.datetime.now()
    hour  = str(now.hour)
    day   = now.strftime("%A")

    data["active_hours"][hour] = data["active_hours"].get(hour, 0) + 1
    data["active_days"][day]   = data["active_days"].get(day, 0) + 1

    if topic:
        data["topics"][topic] = data["topics"].get(topic, 0) + 1

    if mode in ("cloud", "local"):
        data["modes"][mode] = data["modes"].get(mode, 0) + 1

    today = now.strftime("%Y-%m-%d")
    if today not in data.get("streak_days", []):
        data.setdefault("streak_days", []).append(today)
        data["streak_days"] = sorted(data["streak_days"])[-90:]

    if topic:
        proj_key = topic[:40]
        data.setdefault("projects", {})[proj_key] = {
            "last_seen": now.isoformat(),
            "count":     data["projects"].get(proj_key, {}).get("count", 0) + 1,
        }

    data["last_active"] = now.isoformat()
    save_patterns(data)


def get_pattern_context() -> str:
    """Build a personal context string from patterns for prompt injection."""
    data  = load_patterns()
    lines = []

    hours = data.get("active_hours", {})
    if hours:
        peak_hour = max(hours, key=hours.get)
        lines.append(f"Peak activity hour: {peak_hour}:00")

    days = data.get("active_days", {})
    if days:
        peak_day = max(days, key=days.get)
        lines.append(f"Most active day: {peak_day}")

    topics = data.get("topics", {})
    if topics:
        top = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:3]
        lines.append(f"Top topics: {', '.join(t for t, _ in top)}")

    streak = data.get("streak_days", [])
    if streak:
        lines.append(f"Active streak: {len(streak)} days")

    return "\n".join(lines)


def get_stale_projects(days_threshold: int = 7) -> list:
    """Return projects not touched in N days."""
    data    = load_patterns()
    projects = data.get("projects", {})
    now     = datetime.datetime.now()
    stale   = []
    for proj, info in projects.items():
        last = info.get("last_seen")
        if not last:
            continue
        try:
            last_dt  = datetime.datetime.fromisoformat(last)
            days_ago = (now - last_dt).days
            if days_ago >= days_threshold:
                stale.append({
                    "project":  proj,
                    "days_ago": days_ago,
                    "count":    info.get("count", 0),
                })
        except Exception:
            pass
    return sorted(stale, key=lambda x: x["days_ago"], reverse=True)

# =============================================================================
# LAYER 5 — EPISODIC MEMORY (NEW)
# =============================================================================

_episode_lock = threading.Lock()


def load_episodes() -> list:
    """Load all episodic memories."""
    if os.path.exists(EPISODE_FILE):
        try:
            with open(EPISODE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_episodes(episodes: list):
    with _episode_lock:
        atomic_json_write(EPISODE_FILE, episodes[-MAX_EPISODES:])


def store_episode(
    kind:       str,
    summary:    str,
    detail:     str   = "",
    entities:   list  = None,
    valence:    float = 0.0,    # -1.0 (negative) to +1.0 (positive)
    importance: float = 0.5,    # 0.0 (trivial) to 1.0 (critical)
    session_id: str   = "",
) -> str:
    """
    Store a rich episodic memory.

    kind:       "task", "conversation", "discovery", "error", "achievement"
    valence:    emotional tone (-1 bad, 0 neutral, +1 good)
    importance: how significant this episode is
    entities:   list of entity names involved (people, projects, tools)
    """
    episodes = load_episodes()
    ep_id = str(uuid.uuid4())[:8]
    episode = {
        "id":         ep_id,
        "kind":       kind,
        "summary":    summary[:300],
        "detail":     detail[:1000],
        "entities":   entities or [],
        "valence":    round(valence, 2),
        "importance": round(importance, 2),
        "session_id": session_id,
        "at":         datetime.datetime.now().isoformat(),
        "consolidated": False,
    }
    episodes.append(episode)
    save_episodes(episodes)

    # Also write to SQLite for fast querying
    try:
        conn = _db_conn()
        conn.execute(
            "INSERT OR IGNORE INTO episodes (episode_id, kind, summary, detail, entities, valence, importance, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ep_id, kind, summary[:300], detail[:1000],
             json.dumps(entities or []), valence, importance, session_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Check if consolidation is needed
    unconsolidated = [e for e in episodes if not e.get("consolidated")]
    if len(unconsolidated) >= CONSOLIDATION_THRESHOLD:
        _consolidate_episodes_background(episodes)

    return ep_id


def recall_episodes(
    query:      str   = "",
    kind:       str   = "",
    min_importance: float = 0.0,
    n:          int   = 10,
) -> list:
    """Search episodic memory by keyword, kind, or importance."""
    episodes = load_episodes()
    results  = []
    q = query.lower()

    for ep in reversed(episodes):  # most recent first
        if kind and ep.get("kind") != kind:
            continue
        if ep.get("importance", 0) < min_importance:
            continue
        if q:
            searchable = (ep.get("summary", "") + " " + ep.get("detail", "")).lower()
            if not any(word in searchable for word in q.split() if len(word) > 2):
                continue
        results.append(ep)
        if len(results) >= n:
            break

    return results


def get_episode_stats() -> dict:
    """Return statistics about episodic memory."""
    episodes = load_episodes()
    kinds    = {}
    for ep in episodes:
        k = ep.get("kind", "unknown")
        kinds[k] = kinds.get(k, 0) + 1
    avg_valence = sum(e.get("valence", 0) for e in episodes) / len(episodes) if episodes else 0
    return {
        "total":        len(episodes),
        "by_kind":      kinds,
        "avg_valence":  round(avg_valence, 2),
        "unconsolidated": len([e for e in episodes if not e.get("consolidated")]),
    }


def _consolidate_episodes_background(episodes: list):
    """
    Background: compress old episodes into summary entries.
    Old episodes are marked 'consolidated' and a summary episode is added.
    This keeps episodic memory from growing unboundedly.
    """
    def _do_consolidation():
        eps = load_episodes()
        to_consolidate = [e for e in eps if not e.get("consolidated")]
        if len(to_consolidate) < MIN_EPISODES_TO_CONSOLIDATE:
            return

        # Mark them consolidated
        consolidated_ids = set()
        for ep in to_consolidate:
            ep["consolidated"] = True
            consolidated_ids.add(ep["id"])

        # Build a summary
        kinds_count = {}
        positive = sum(1 for e in to_consolidate if e.get("valence", 0) > 0.2)
        negative = sum(1 for e in to_consolidate if e.get("valence", 0) < -0.2)
        for ep in to_consolidate:
            k = ep.get("kind", "unknown")
            kinds_count[k] = kinds_count.get(k, 0) + 1

        summary_ep = {
            "id":           f"summary_{str(uuid.uuid4())[:6]}",
            "kind":         "consolidation_summary",
            "summary":      (
                f"Consolidated {len(to_consolidate)} episodes. "
                f"Tasks: {kinds_count.get('task', 0)}, "
                f"Errors: {kinds_count.get('error', 0)}, "
                f"Discoveries: {kinds_count.get('discovery', 0)}. "
                f"Positive outcomes: {positive}, Negative: {negative}."
            ),
            "detail":       json.dumps(kinds_count),
            "entities":     [],
            "valence":      round((positive - negative) / max(len(to_consolidate), 1), 2),
            "importance":   0.7,
            "session_id":   "",
            "at":           datetime.datetime.now().isoformat(),
            "consolidated": False,
        }
        eps.append(summary_ep)
        save_episodes(eps)

    t = threading.Thread(target=_do_consolidation, daemon=True)
    t.start()

# =============================================================================
# ENTITY GRAPH (NEW)
# =============================================================================

_entity_lock = threading.Lock()


def load_entity_graph() -> dict:
    """Load the entity graph."""
    if os.path.exists(ENTITY_GRAPH_FILE):
        try:
            with open(ENTITY_GRAPH_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"entities": {}, "relations": []}


def save_entity_graph(graph: dict):
    with _entity_lock:
        atomic_json_write(ENTITY_GRAPH_FILE, graph)


def upsert_entity(
    name:       str,
    kind:       str   = "concept",   # "person", "project", "tool", "topic", "place"
    attributes: dict  = None,
):
    """Add or update an entity in the knowledge graph."""
    graph = load_entity_graph()
    entities = graph.setdefault("entities", {})
    key = name.lower().strip()

    if key in entities:
        entities[key]["mention_count"] = entities[key].get("mention_count", 0) + 1
        entities[key]["last_seen"] = datetime.datetime.now().isoformat()
        if attributes:
            entities[key].setdefault("attributes", {}).update(attributes)
    else:
        entities[key] = {
            "name":          name,
            "kind":          kind,
            "mention_count": 1,
            "first_seen":    datetime.datetime.now().isoformat(),
            "last_seen":     datetime.datetime.now().isoformat(),
            "attributes":    attributes or {},
        }

    # Prune if too large
    if len(entities) > 500:
        # Remove least mentioned entities
        sorted_keys = sorted(entities, key=lambda k: entities[k].get("mention_count", 0))
        for k in sorted_keys[:50]:
            del entities[k]

    graph["entities"] = entities
    save_entity_graph(graph)


def relate_entities(entity_a: str, entity_b: str, relation: str):
    """Record a relationship between two entities."""
    graph = load_entity_graph()
    relations = graph.setdefault("relations", [])
    key_a = entity_a.lower().strip()
    key_b = entity_b.lower().strip()
    # Deduplicate
    for r in relations:
        if (r["from"] == key_a and r["to"] == key_b and r["relation"] == relation):
            r["strength"] = r.get("strength", 1) + 1
            r["last_seen"] = datetime.datetime.now().isoformat()
            save_entity_graph(graph)
            return
    relations.append({
        "from":     key_a,
        "to":       key_b,
        "relation": relation,
        "strength": 1,
        "last_seen": datetime.datetime.now().isoformat(),
    })
    if len(relations) > 1000:
        relations.sort(key=lambda r: r.get("strength", 0), reverse=True)
        graph["relations"] = relations[:800]
    save_entity_graph(graph)


def get_entity_context(name: str) -> str:
    """Get all known info about an entity as a string."""
    graph    = load_entity_graph()
    entities = graph.get("entities", {})
    key      = name.lower().strip()
    info     = entities.get(key)
    if not info:
        return ""
    lines = [f"Entity: {info['name']} ({info['kind']})"]
    lines.append(f"Mentioned {info['mention_count']} times, last seen {info.get('last_seen', '')[:10]}")
    attrs = info.get("attributes", {})
    if attrs:
        for k, v in list(attrs.items())[:5]:
            lines.append(f"  {k}: {v}")
    # Find relations
    relations = graph.get("relations", [])
    related = [r for r in relations if r["from"] == key or r["to"] == key][:5]
    if related:
        lines.append("Relations:")
        for r in related:
            other = r["to"] if r["from"] == key else r["from"]
            lines.append(f"  {r['relation']} → {other}")
    return "\n".join(lines)


def get_top_entities(n: int = 10, kind: str = "") -> list:
    """Return most frequently mentioned entities."""
    graph    = load_entity_graph()
    entities = graph.get("entities", {})
    items    = [v for v in entities.values() if (not kind or v.get("kind") == kind)]
    items.sort(key=lambda e: e.get("mention_count", 0), reverse=True)
    return items[:n]

# =============================================================================
# MULTI-LAYER SEARCH (NEW)
# =============================================================================

def fuzzy_recall(query: str, n: int = 5) -> dict:
    """
    Search across all memory layers simultaneously.
    Returns results from each layer.
    """
    q = query.lower()
    results = {
        "facts":    [],
        "episodes": [],
        "entities": [],
        "patterns": [],
    }

    # Layer 1: facts
    results["facts"] = recall_relevant(query, n=n)

    # Layer 5: episodes
    eps = recall_episodes(query=query, n=n)
    results["episodes"] = [{"summary": e["summary"], "at": e["at"][:10], "kind": e["kind"]} for e in eps]

    # Entity graph
    graph    = load_entity_graph()
    entities = graph.get("entities", {})
    matching = [v for k, v in entities.items() if any(w in k for w in q.split() if len(w) > 2)]
    matching.sort(key=lambda e: e.get("mention_count", 0), reverse=True)
    results["entities"] = [{"name": e["name"], "kind": e["kind"], "count": e["mention_count"]}
                           for e in matching[:n]]

    # Pattern topics
    patterns = load_patterns()
    topics   = patterns.get("topics", {})
    matching_topics = [(t, c) for t, c in topics.items() if any(w in t.lower() for w in q.split() if len(w) > 2)]
    matching_topics.sort(key=lambda x: x[1], reverse=True)
    results["patterns"] = [{"topic": t, "count": c} for t, c in matching_topics[:n]]

    return results

# =============================================================================
# BRIEFING STORAGE
# =============================================================================

_briefing_lock = threading.Lock()


def load_briefing() -> dict:
    if os.path.exists(BRIEFING_FILE):
        try:
            with open(BRIEFING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_briefing(briefing: dict):
    with _briefing_lock:
        atomic_json_write(BRIEFING_FILE, briefing)

# =============================================================================
# SEMANTIC SEARCH — thin wrappers over vector_store.py
# =============================================================================
# Previously this block ran an old, broken chromadb API (duckdb+parquet which
# was removed in chromadb 0.4+) and _init_chroma() was never even called, so
# everything here was dead code. Now it routes through vector_store.

def _init_chroma():
    """Kept for backward compatibility. vector_store auto-initialises on import."""
    return _VSTORE_OK


def semantic_store(text: str, metadata: dict = None):
    """Store a piece of text in the semantic layer. Used widely in the codebase."""
    if not _VSTORE_OK:
        return
    try:
        _vstore.remember(text, kind=(metadata or {}).get("kind", "general"), metadata=metadata)
    except Exception:
        pass


def semantic_search(query: str, n: int = SEMANTIC_TOP_K) -> list:
    """Semantic search — returns list of matching text strings."""
    if not _VSTORE_OK:
        return []
    try:
        hits = _vstore.recall(query, n=n)
        return [h["text"] for h in hits]
    except Exception:
        return []


def semantic_search_rich(query: str, n: int = SEMANTIC_TOP_K, kind: str = None) -> list:
    """Semantic search returning full hit dicts (text, score, metadata)."""
    if not _VSTORE_OK:
        return []
    try:
        return _vstore.recall(query, n=n, kind=kind)
    except Exception:
        return []


# ── Last-action tracking (in-memory, per session, not persisted to disk) ──
_last_action_store: dict = {}
_last_action_lock  = threading.Lock()

def set_last_action(session_id: str, intent: dict, result: dict):
    """Remember the last intent+result for this session."""
    with _last_action_lock:
        _last_action_store[session_id] = {
            "intent": intent,
            "result": result,
            "at":     datetime.datetime.now().isoformat(),
        }

def get_last_action(session_id: str) -> dict | None:
    with _last_action_lock:
        return _last_action_store.get(session_id)
