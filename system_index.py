"""
system_index.py — Dynamic system-wide app + file + directory indexer.
Scans all user folders up to 5 levels deep, skips build/noise dirs.
Refreshes every 10 minutes in a background thread.
"""
import os, glob, time, threading, platform

_BASE        = platform.system()
_index       = {"apps": {}, "files": {}, "dirs": {}, "built_at": 0.0}
_lock        = threading.Lock()
_REFRESH_SEC = 600   # rebuild every 10 minutes

# Directories that produce noise / slow scans with no useful files
_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "venv", ".venv", "env", ".env",
    "dist", "build", "obj", "bin", "target",
    ".idea", ".vs", ".vscode",
    "$recycle.bin", "recycler",
    "temp", "tmp", "cache", ".cache",
    "thumbs.db", "desktop.ini",
}


def _should_skip(name: str) -> bool:
    return name.lower() in _SKIP_DIRS or name.startswith(".")


# ── App scanner ───────────────────────────────────────────────────────────────

def _scan_apps_windows() -> dict:
    apps = {}
    # Start Menu shortcuts (.lnk) — covers every installed app
    for d in [
        os.path.expandvars(r'%ProgramData%\Microsoft\Windows\Start Menu\Programs'),
        os.path.expandvars(r'%APPDATA%\Microsoft\Windows\Start Menu\Programs'),
    ]:
        for lnk in glob.glob(os.path.join(d, '**', '*.lnk'), recursive=True):
            name = os.path.splitext(os.path.basename(lnk))[0].lower().strip()
            apps[name] = lnk

    # Top-level .exe scan in Program Files dirs
    for d in [
        os.environ.get("ProgramFiles",       r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)",  r"C:\Program Files (x86)"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
        os.path.expandvars(r"%APPDATA%\Microsoft\WindowsApps"),
    ]:
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            sub = os.path.join(d, entry)
            if os.path.isdir(sub):
                for exe in glob.glob(os.path.join(sub, "*.exe")):
                    name = os.path.splitext(os.path.basename(exe))[0].lower()
                    apps.setdefault(name, exe)
    return apps


# ── File + directory scanner ─────────────────────────────────────────────────

def _scan_files_user() -> tuple:
    """
    Returns (files_dict, dirs_dict) keyed by lowercase name → full path.
    Scans all user folders up to 5 levels deep, skipping noise dirs.
    """
    files: dict = {}
    dirs:  dict = {}
    home   = os.path.expanduser("~")

    # Build scan roots — start with known important locations
    roots = [
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Music"),
        os.path.join(home, "Videos"),
        os.path.join(home, "OneDrive"),       # covers OneDrive\Desktop, Documents, etc.
        home,                                  # catches direct home-level dirs (projects, code, etc.)
    ]
    # Add all direct subdirectories of home that aren't already covered
    try:
        for entry in os.listdir(home):
            full = os.path.join(home, entry)
            if os.path.isdir(full) and not _should_skip(entry) and full not in roots:
                roots.append(full)
    except OSError:
        pass

    seen_roots = set()

    for root_dir in roots:
        if not os.path.isdir(root_dir):
            continue
        # Avoid scanning the same physical location twice
        try:
            real = os.path.realpath(root_dir)
        except OSError:
            real = root_dir
        if real in seen_roots:
            continue
        seen_roots.add(real)

        # Register the root dir itself
        dname = os.path.basename(root_dir)
        if dname:
            dirs.setdefault(dname.lower(), root_dir)

        for root, subdirs, fnames in os.walk(root_dir, followlinks=False):
            # Compute depth relative to root_dir
            depth = root[len(root_dir):].count(os.sep)

            # Prune unwanted subdirs in place (modifies the walk)
            subdirs[:] = [sd for sd in subdirs if not _should_skip(sd)]

            # Cap depth at 5 levels (plenty for any real user folder)
            if depth >= 5:
                subdirs[:] = []
                continue

            # Index all subdirs at this level
            for sd in subdirs:
                dirs.setdefault(sd.lower(), os.path.join(root, sd))

            # Index all files at this level
            for fname in fnames:
                if fname.startswith("."):
                    continue
                files.setdefault(fname.lower(), os.path.join(root, fname))

    return files, dirs


# ── Index build / refresh ─────────────────────────────────────────────────────

def rebuild_index() -> dict:
    with _lock:
        if _BASE == "Windows":
            _index["apps"] = _scan_apps_windows()
        files, dirs = _scan_files_user()
        _index["files"]    = files
        _index["dirs"]     = dirs
        _index["built_at"] = time.time()
    return {
        "apps":  len(_index["apps"]),
        "files": len(_index["files"]),
        "dirs":  len(_index["dirs"]),
    }


def get_index() -> dict:
    if not _index["files"] or (time.time() - _index["built_at"]) > _REFRESH_SEC:
        rebuild_index()
    return _index


# ── Lookup functions ──────────────────────────────────────────────────────────

_STOP_WORDS_FOR_APP_LOOKUP = {
    # Pronouns and articles that can fuzzy-match Start Menu entries via
    # naive substring (e.g. "it" → "speech recognition", "or" → "explorer",
    # "the" → "weather"). The user almost never means an actual app when
    # they say one of these in isolation, so refuse to resolve them.
    "it", "that", "this", "the", "a", "an", "one", "thing",
    "or", "and", "but", "yes", "no",
    "i", "me", "my", "you", "your", "we", "us", "they",
    "is", "in", "on", "at", "to", "of", "by",
}


def find_app(query: str) -> str | None:
    """Find an installed app by name. Returns path to .lnk or .exe, or None.

    Conservative matching to avoid the "open it" → Speech Recognition bug:
      - Reject queries shorter than 3 chars or that are common stop-words.
      - Substring match requires a word-boundary hit, not any in-name
        substring (so "it" no longer matches "speech recogn**it**ion").
      - Word-set match unchanged — still helpful for "visual studio code"
        → "Visual Studio Code" or "vs code" → "code".
    """
    if not query:
        return None
    q = query.lower().strip()
    if not q:
        return None
    # Refuse trivially ambiguous queries.
    if len(q) < 3 or q in _STOP_WORDS_FOR_APP_LOOKUP:
        return None

    idx = get_index()
    if q in idx["apps"]:
        return idx["apps"][q]

    # Word-boundary substring match: the query must appear as its own word
    # (or as a prefix of a word) in the app name. Avoids "it" matching
    # "speech recognition" while still letting "code" match "Visual Studio
    # Code" and "edge" match "Microsoft Edge".
    for name, path in idx["apps"].items():
        if any(w == q or w.startswith(q) for w in name.split()):
            return path

    # Word-set match — every word in the query must be a word in the name.
    q_words = set(q.split())
    if q_words:
        for name, path in idx["apps"].items():
            if q_words.issubset(set(name.split())):
                return path
    return None


def find_file(query: str) -> str | None:
    """Find a file by name across all indexed user folders. Returns full path or None."""
    idx = get_index()
    q   = query.lower().strip()
    # Exact name match
    if q in idx["files"]:
        return idx["files"][q]
    # Substring match
    for name, path in idx["files"].items():
        if q in name:
            return path
    return None


def find_dir(query: str) -> str | None:
    """Find a directory by name across all indexed user folders. Returns full path or None."""
    idx = get_index()
    q   = query.lower().strip()
    # Exact match
    if q in idx["dirs"]:
        return idx["dirs"][q]
    # Substring match
    for name, path in idx["dirs"].items():
        if q in name:
            return path
    return None


def search_files(query: str, limit: int = 10) -> list:
    """Return up to `limit` file paths whose names contain the query string."""
    idx     = get_index()
    q       = query.lower().strip()
    results = []
    for name, path in idx["files"].items():
        if q in name:
            results.append(path)
            if len(results) >= limit:
                break
    return results


def search_dirs(query: str, limit: int = 10) -> list:
    """Return up to `limit` directory paths whose names contain the query string."""
    idx     = get_index()
    q       = query.lower().strip()
    results = []
    for name, path in idx["dirs"].items():
        if q in name:
            results.append(path)
            if len(results) >= limit:
                break
    return results


def start_index_refresher():
    """Start a daemon thread that rebuilds the index every _REFRESH_SEC seconds."""
    def _loop():
        while True:
            try:
                rebuild_index()
            except Exception as e:
                print(f"[SysIndex] refresh error: {e}")
            time.sleep(_REFRESH_SEC)
    threading.Thread(target=_loop, daemon=True, name="sys_index").start()
