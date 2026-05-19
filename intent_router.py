"""
intent_router.py — Pre-LLM action intent detection for Ultron-J.

Intercepts natural-language commands and routes them directly to
action_engine / computer_control, bypassing the LLM entirely.
Covers: file CRUD, rename, copy, move, zip, run scripts, list dirs,
        app/file open, media, search, and repeat-last.
"""
import re
import os
import shutil


# ── Safety ────────────────────────────────────────────────────────────────────

_PROTECTED_PATHS = [
    "system32", "windows", "program files",
    ".venv", "venv", "site-packages",
    "ultron-web", "ultron_web",
    "appdata\\roaming\\microsoft",
    "appdata\\local\\microsoft",
]

def _is_protected(path: str) -> bool:
    pl = path.lower().replace("/", "\\")
    return any(p in pl for p in _PROTECTED_PATHS)


# ── Path helpers ──────────────────────────────────────────────────────────────

def _resolve_default_path(filename: str) -> str:
    """
    If filename has no directory component, place it on the user's Desktop.
    Prefers OneDrive Desktop, falls back to plain Desktop, then home dir.
    """
    if os.sep in filename or "/" in filename:
        return os.path.expandvars(os.path.expanduser(filename))
    home = os.path.expanduser("~")
    for candidate in [
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Desktop"),
    ]:
        if os.path.isdir(candidate):
            return os.path.join(candidate, filename)
    return os.path.join(home, filename)


def _resolve_dest(dest: str) -> str:
    """
    Resolve a destination string to a full directory path.
    Handles shorthand names (desktop, downloads, onedrive…),
    env vars, ~ expansion, and index lookup for project folders.
    """
    home = os.path.expanduser("~")
    _od  = os.path.join(home, "OneDrive")

    def _od_or(sub, fallback):
        p = os.path.join(_od, sub)
        return p if os.path.isdir(p) else os.path.join(home, fallback)

    shortcuts = {
        "desktop":   _od_or("Desktop",   "Desktop"),
        "documents": _od_or("Documents", "Documents"),
        "downloads": os.path.join(home, "Downloads"),
        "onedrive":  _od,
        "pictures":  _od_or("Pictures",  "Pictures"),
        "music":     os.path.join(home, "Music"),
        "videos":    os.path.join(home, "Videos"),
        "home":      home,
    }
    dl = dest.strip().lower()
    if dl in shortcuts:
        return shortcuts[dl]

    expanded = os.path.expandvars(os.path.expanduser(dest.strip()))
    if os.path.isdir(expanded):
        return expanded

    # Try directory index
    found = _find_dir(dest.strip())
    if found:
        return found

    return expanded   # let caller surface the error if it doesn't exist


def _find(query: str) -> str | None:
    """Find a file by name in the system index. Returns full path or None."""
    try:
        from system_index import find_file
        return find_file(query)
    except Exception:
        return None


def _find_dir(query: str) -> str | None:
    """Find a directory by name in the system index. Returns full path or None."""
    try:
        from system_index import find_dir
        return find_dir(query)
    except Exception:
        return None


def _find_any(query: str) -> str | None:
    """Find file OR directory — file takes priority."""
    return _find(query) or _find_dir(query)


def _ensure_ext(filename: str) -> str:
    """Add .txt extension if filename has none."""
    common = (".txt", ".md", ".py", ".html", ".js", ".json",
              ".csv", ".yaml", ".yml", ".sh", ".bat", ".ps1")
    if not any(filename.endswith(e) for e in common):
        return filename + ".txt"
    return filename


# ── Pattern table ─────────────────────────────────────────────────────────────
# Order matters — first match wins. More specific patterns first.

_PATTERNS = [

    # ── repeat last (highest priority) ────────────────────────────────────────
    (r"^(?:do (?:it|that) )?(?:again|once more|one more time|repeat)$",
     "repeat_last"),
    (r"^(?:can you )?(?:please )?repeat(?: that)?$", "repeat_last"),

    # ── help me ───────────────────────────────────────────────────────────────
    (r"^(?:please )?help me(?:\s|$)", "help_me_now"),
    (r"^i(?:'m|\s+am)\s+stuck", "help_me_now"),
    (r"^(?:what )?do i do (?:now|next)", "help_me_now"),

    # ── run / execute script ──────────────────────────────────────────────────
    (r"^(?:run|execute) (?:my |the |file )?[\"']?([\w\-\. ]+\.(?:py|bat|sh|js|ps1))[\"']?$",
     "run_script"),

    # ── read / show file ──────────────────────────────────────────────────────
    (r"^read (?:the |my |the file |file )?[\"']?([\w\-\. ]+\.\w{2,5})[\"']?$",
     "read_file"),
    (r"^show (?:me |the |my )?(?:contents? of |file )?[\"']?([\w\-\. ]+\.\w{2,5})[\"']?$",
     "read_file"),
    (r"^(?:cat|print|display) (?:the |my |file )?[\"']?([\w\-\. ]+\.\w{2,5})[\"']?$",
     "read_file"),

    # ── write content to file (overwrite) ─────────────────────────────────────
    (r"^write [\"']?(.+?)[\"']? (?:to|into) (?:the |my |file )?[\"']?([\w\-\. ]+)[\"']?$",
     "write_file"),

    # ── append / add content to file ──────────────────────────────────────────
    (r"^(?:add|append) [\"']?(.+?)[\"']? (?:to|in|into) (?:the |my |file )?[\"']?([\w\-\. ]+)[\"']?$",
     "append_to_file"),
    (r"^edit (?:the |my |file )?[\"']?([\w\-\. ]+)[\"']?[: ]+(.+)$",
     "edit_file"),

    # ── find / locate ─────────────────────────────────────────────────────────
    (r"^(?:find|locate|where is|where's|find me) (?:the |my |file |folder )?[\"']?([\w\-\. ]+)[\"']?\s*(?:file|folder)?$",
     "find_file_query"),

    # ── delete folder (before delete file — more specific) ────────────────────
    (r"^(?:delete|remove|erase) (?:the |my )?(?:folder|directory|dir) [\"']?([\w\-\. ]+)[\"']?$",
     "delete_folder"),

    # ── delete file ───────────────────────────────────────────────────────────
    (r"^(?:delete|remove|erase|trash) (?:the |my |file )?[\"']?([\w\-\. ]+)[\"']?$",
     "delete_file"),

    # ── rename ────────────────────────────────────────────────────────────────
    (r"^rename (?:the |my |file |folder )?[\"']?([\w\-\. ]+)[\"']? (?:to|as) [\"']?([\w\-\. ]+)[\"']?$",
     "rename_file"),

    # ── copy ──────────────────────────────────────────────────────────────────
    (r"^copy (?:the |my |file |folder )?[\"']?([\w\-\. ]+)[\"']? (?:to|into) (.+)$",
     "copy_file"),

    # ── move ──────────────────────────────────────────────────────────────────
    (r"^move (?:the |my |file |folder )?[\"']?([\w\-\. ]+)[\"']? (?:to|into) (.+)$",
     "move_file"),

    # ── zip / compress ────────────────────────────────────────────────────────
    (r"^(?:zip|compress|archive) (?:the |my |folder |directory )?[\"']?([\w\-\. ]+)[\"']?(?:\s+(?:to|as|into)\s+[\"']?([\w\-\. ]+)[\"']?)?$",
     "zip_item"),

    # ── list directory ────────────────────────────────────────────────────────
    # `list|ls|dir` are directory verbs — but with no qualifier and an unrooted
    # argument the rule fired on natural-language sentences ("list 30 fruits
    # one per line" was treated as a directory request). Same fix as the
    # `show` rule below: either an explicit dir-context word must appear,
    # OR the argument must look like a path (contains /, \, ~, :, or is a
    # well-known folder name).
    (r"^(?:list|ls|dir) (?:files? (?:in |inside |from |of )|contents? (?:of )|(?:the |my )?(?:folder |directory ))[\"']?([\w\-\. \/\\~%:]+)[\"']?(?:\s+(?:folder|directory|dir))?$",
     "list_dir"),
    (r"^(?:list|ls|dir) [\"']?([\w\-\. ]*[\/\\~:][\w\-\. \/\\~%:]*)[\"']?(?:\s+(?:folder|directory|dir))?$",
     "list_dir"),
    (r"^(?:list|ls|dir) [\"']?(downloads|documents|desktop|pictures|videos|music|home|onedrive|userprofile)[\"']?$",
     "list_dir"),
    # `show` is ambiguous — require an explicit directory-context word
    # ("show files X", "show folder X", "show contents of X"); bare "show X"
    # falls through to LLM (e.g. "show cricket score").
    (r"^show (?:files? (?:in |inside |from |of )|contents? (?:of )|(?:the |my )?(?:folder |directory ))[\"']?([\w\-\. \/\\~%:]+)[\"']?(?:\s+(?:folder|directory|dir))?$",
     "list_dir"),
    (r"^(?:what(?:'s| is) in|show me) (?:(?:the |my )?(?:folder |directory )|files? (?:in |inside |from |of ))[\"']?([\w\-\. \/\\~%:]+)[\"']?(?:\s+(?:folder|directory|dir))?$",
     "list_dir"),

    # ── file creation WITH explicit path ──────────────────────────────────────
    (r"create (?:a |an |new )?(?:file|text file|document) "
     r"(?:named |called )?[\"']?([\w\-\. ]+)[\"']? (?:in |at |inside )(.+)",
     "create_file_named"),
    (r"create (?:a |an |new )?(?:file|text file|document) (?:in |at |inside )(.+)",
     "create_file_in_dir"),

    # ── file creation WITHOUT path (defaults to Desktop) ─────────────────────
    (r"^create (?:a |an |new )?(?:file|text file|document) (?:named |called )?[\"']?([\w\-\. ]+)[\"']?$",
     "create_file_name_only"),
    (r"^make (?:a |an |new )?(?:file|text file|document) (?:named |called )?[\"']?([\w\-\. ]+)[\"']?$",
     "create_file_name_only"),

    # ── open file by name (has extension — before open_app) ───────────────────
    (r"^open (?:the |my |the file |file )?[\"']?([\w\-\. ]+\.\w{2,5})[\"']?$",
     "open_file"),

    # ── folder open ───────────────────────────────────────────────────────────
    (r"^open (?:the )?(?:folder|directory) (.+)",
     "open_folder"),

    # ── multi-step: open SITE and search QUERY (must precede open_app) ────────
    # groups: (site, query) — execute_intent for "open_and_search" inverts.
    (r"^open\s+(\w+)\s+and\s+search\s+(?:for\s+)?(.+)$", "open_and_search"),

    # ── app opening ───────────────────────────────────────────────────────────
    (r"^open (?:the )?([\w\-\. ]+?)(?: app| application)?$", "open_app"),
    (r"^launch (?:the )?([\w\-\. ]+)$", "open_app"),
    (r"^start (?:the )?([\w\-\. ]+?)(?: app| application)?$", "open_app"),

    # ── time / date ───────────────────────────────────────────────────────────
    (r"^(?:what(?:'s| is) (?:the )?)?(?:current |local )?time(?:\s+(?:now|right\s+now|for\s+me|here))*[?]?$", "get_time"),
    (r"^what time is it(?:\s+(?:for\s+me|right\s+now|now|here|in\s+\w+(?:\s+\w+)*))*[?]?$", "get_time"),
    (r"^what(?:'s| is) (?:the )?(?:current |local )?time(?:\s+(?:now|right\s+now|for\s+me|here|in\s+\w+(?:\s+\w+)*))*[?]?$", "get_time"),
    (r"^(?:tell me|show me)(?: the)?(?: current| local)? time[?]?$", "get_time"),
    (r"^clock[?]?$", "get_time"),
    (r"^what(?:'s| is) (?:today'?s? |the )?date(?:\s+today)?[?]?$", "get_date"),
    (r"^(?:what day is (?:it|today)|today'?s? date)[?]?$", "get_date"),

    # ── screenshot ────────────────────────────────────────────────────────────
    (r"^(?:take (?:a )?)?screenshot$", "take_screenshot"),
    (r"^(?:take (?:a )?)?screen(?:shot|cap(?:ture)?)$", "take_screenshot"),
    (r"^capture (?:the )?screen$", "take_screenshot"),

    # ── volume ────────────────────────────────────────────────────────────────
    (r"^(?:turn |go )?volume up(?:\s+\d+\s*%?)?$", "volume_up"),
    (r"^(?:increase|raise|boost|louder)(?: (?:the )?volume)?$", "volume_up"),
    (r"^(?:turn |go )?volume down(?:\s+\d+\s*%?)?$", "volume_down"),
    (r"^(?:decrease|lower|reduce|quieter)(?: (?:the )?volume)?$", "volume_down"),
    (r"^(?:mute|unmute|toggle (?:the )?mute)(?:\s+(?:audio|sound|mic|volume))?$", "volume_mute"),

    # ── media controls ────────────────────────────────────────────────────────
    (r"^pause(?: (?:the )?(?:video|music|song|playback|media))?$", "media_pause"),
    (r"^(?:resume|unpause|continue)(?: (?:the )?(?:video|music|song|playback|media))?$", "media_play"),
    (r"^(?:next|skip)(?: (?:track|song|video))?$", "media_next"),
    (r"^(?:previous|prev|back|go back)(?: (?:track|song|video))?$", "media_prev"),

    # ── window control ────────────────────────────────────────────────────────
    (r"^minimize(?: (?:this |the )?(?:window|app|application))?$", "minimize_window"),
    (r"^maximize(?: (?:this |the )?(?:window|app|application))?$", "maximize_window"),
    (r"^close (?:this |the )?(?:window|app|application|tab)$", "close_window"),

    # ── press key ─────────────────────────────────────────────────────────────
    (r"^press (?:the )?escape(?: key)?$", "press_escape"),
    (r"^(?:press (?:the )?)?(?:enter|return)(?: key)?$", "press_enter"),
    (r"^press (?:the )?tab(?: key)?$", "press_tab"),
    (r"^press (?:the )?backspace(?: key)?$", "press_backspace"),
    (r"^press (?:the )?delete(?: key)?$", "press_delete"),
    (r"^press (?:the )?space(?:bar)?(?: key)?$", "press_space"),
    (r"^press (?:the )?([a-z][0-9]?|f[0-9]{1,2})(?: key)?$", "press_key_name"),

    # ── scroll ────────────────────────────────────────────────────────────────
    (r"^scroll down(?:\s+(\d+))?$", "scroll_down"),
    (r"^scroll up(?:\s+(\d+))?$", "scroll_up"),

    # ── type text ─────────────────────────────────────────────────────────────
    (r"^type(?:\s+(?:this|the text|text))?[: ]+(.+)$", "type_text_cmd"),

    # ── media play ────────────────────────────────────────────────────────────
    (r"play (.+?) (?:on|in) ([\w\-\.]+)", "play_media_on"),
    (r"play (.+)", "play_media"),

    # ── search ────────────────────────────────────────────────────────────────
    # NOTE: open_and_search lives further up (above open_app) so the regex
    # engine doesn't fall through to open_app first.
    (r"search (?:for )?(.+?) (?:on|in|using) ([\w\-\.]+)", "search_on"),
    (r"search (?:the )?(?:web )?(?:for )?(.+)", "search_web"),
]


# ── Intent detector ───────────────────────────────────────────────────────────

def detect_intent(message: str) -> dict | None:
    msg = message.strip()
    if not msg or len(msg) > 300:
        return None
    for pattern, action_type in _PATTERNS:
        m = re.match(pattern, msg, re.IGNORECASE)
        if m:
            return {
                "type":   action_type,
                "groups": m.groups(),
                "raw":    message,
            }
    return None


# ── Intent executor ───────────────────────────────────────────────────────────

def execute_intent(intent: dict) -> dict:
    from action_engine import execute_action
    from computer_control import open_app as _open_app

    t = intent["type"]
    g = intent["groups"]

    # ── open app ──────────────────────────────────────────────────────────────
    if t == "open_app":
        name = g[0].strip()
        # Strip possessive prefix ("my resume" → "resume")
        clean = re.sub(r"^(?:my|the|a|an)\s+", "", name, flags=re.IGNORECASE).strip()
        result = _open_app(clean)
        if not result.get("success") and clean != name:
            result = _open_app(name)
        # If still failed, try searching file index for a matching document
        if not result.get("success"):
            doc_path = _find(clean) or _find(name)
            if doc_path and os.path.exists(doc_path):
                try:
                    os.startfile(doc_path)
                    return {"success": True, "app": doc_path,
                            "result": f"Opened {os.path.basename(doc_path)}"}
                except Exception as e:
                    return {"success": False, "error": str(e)}
        return result

    # ── open file by name ─────────────────────────────────────────────────────
    if t == "open_file":
        filename = g[0].strip()
        path = _find(filename) or _resolve_default_path(filename)
        if not os.path.exists(path):
            return {"success": False,
                    "error": f"'{filename}' not found. Try: find {filename}"}
        try:
            os.startfile(path)
            return {"success": True, "app": path,
                    "result": f"Opened {os.path.basename(path)}\n`{path}`"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── open folder ───────────────────────────────────────────────────────────
    if t == "open_folder":
        target = g[0].strip()
        path   = _find_dir(target) or _resolve_dest(target)
        if os.path.isdir(path):
            try:
                os.startfile(path)
                return {"success": True, "result": f"Opened folder: `{path}`"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": f"Folder '{target}' not found."}

    # ── read file ─────────────────────────────────────────────────────────────
    if t == "read_file":
        filename = g[0].strip()
        path = _find(filename) or _resolve_default_path(filename)
        if not os.path.exists(path):
            return {"success": False,
                    "error": f"'{filename}' not found. Try: find {filename}"}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(4000)
            size      = os.path.getsize(path)
            truncated = size > 4000
            suffix    = f"\n\n…[{size} bytes total — ask me to read more]" if truncated else ""
            display   = (f"**{os.path.basename(path)}**\n"
                         f"`{path}`\n\n"
                         f"```\n{content}{suffix}\n```")
            return {"success": True, "result": display, "path": path}
        except Exception as e:
            return {"success": False, "error": f"read failed: {e}"}

    # ── write to file (overwrite) ─────────────────────────────────────────────
    if t == "write_file":
        content, filename = g[0].strip(), g[1].strip()
        filename = _ensure_ext(filename)
        path = _find(filename) or _resolve_default_path(filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            stat = os.stat(path)
            return {"success": True,
                    "result": f"Written to `{path}` ({stat.st_size} bytes)",
                    "verified_path": path, "verified_size": stat.st_size}
        except Exception as e:
            return {"success": False, "error": f"write failed: {e}"}

    # ── append content to file ────────────────────────────────────────────────
    if t in ("append_to_file", "edit_file"):
        if t == "append_to_file":
            content, filename = g[0].strip(), g[1].strip()
        else:  # edit_file: "edit notes.txt: add this"
            filename, content = g[0].strip(), g[1].strip()
        filename = _ensure_ext(filename)
        path = _find(filename) or _resolve_default_path(filename)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n" + content)
            stat = os.stat(path)
            return {"success": True,
                    "result": f"Appended to `{path}` (now {stat.st_size} bytes)",
                    "verified_path": path}
        except Exception as e:
            return {"success": False, "error": f"append failed: {e}"}

    # ── find / locate file or folder ──────────────────────────────────────────
    if t == "find_file_query":
        query = g[0].strip()
        path  = _find_any(query)
        if path:
            kind = "Folder" if os.path.isdir(path) else "File"
            return {"success": True,
                    "result": f"{kind} found: **{os.path.basename(path)}**\n`{path}`",
                    "path": path}
        try:
            from system_index import search_files, search_dirs
            matches = search_files(query, 5) + search_dirs(query, 5)
            if matches:
                listing = "\n".join(f"`{p}`" for p in matches[:8])
                return {"success": True,
                        "result": f"Possible matches for **{query}**:\n{listing}"}
        except Exception:
            pass
        return {"success": False,
                "error": f"'{query}' not found in Desktop, Documents, Downloads, or any user folder."}

    # ── create file — name only → Desktop ────────────────────────────────────
    if t == "create_file_name_only":
        filename  = _ensure_ext(g[0].strip())
        full_path = _resolve_default_path(filename)
        return execute_action("create_file", {"path": full_path, "content": ""})

    # ── create file — name + explicit dir (+ optional content) ───────────────
    if t == "create_file_named":
        filename        = _ensure_ext(g[0].strip())
        dir_and_content = g[1].strip()
        _cm = re.search(r'\s+with\s+content\s+(.+?)\s*$', dir_and_content, re.IGNORECASE)
        if _cm:
            content = _cm.group(1).strip().strip('"\'')
            dirpart = dir_and_content[:_cm.start()].strip()
        else:
            content = ""
            dirpart = dir_and_content
        dirpath   = _resolve_dest(dirpart)
        full_path = os.path.join(dirpath, filename)
        return execute_action("create_file", {"path": full_path, "content": content})

    # ── create file — dir only, generic name ──────────────────────────────────
    if t == "create_file_in_dir":
        dirpath   = _resolve_dest(g[0].strip())
        full_path = os.path.join(dirpath, "new_file.txt")
        return execute_action("create_file", {"path": full_path, "content": ""})

    # ── delete file ───────────────────────────────────────────────────────────
    if t == "delete_file":
        filename = g[0].strip()
        path = _find(filename) or _resolve_default_path(filename)
        if not os.path.exists(path):
            return {"success": False, "error": f"'{filename}' not found."}
        if os.path.isdir(path):
            return {"success": False,
                    "error": f"'{filename}' is a folder. Use: delete folder {filename}"}
        if _is_protected(path):
            return {"success": False,
                    "error": f"Blocked: '{path}' is a protected system file."}
        try:
            size = os.path.getsize(path)
            os.remove(path)
            return {"success": True,
                    "result": f"Deleted `{path}` ({size} bytes)"}
        except Exception as e:
            return {"success": False, "error": f"delete failed: {e}"}

    # ── delete folder ─────────────────────────────────────────────────────────
    if t == "delete_folder":
        dirname = g[0].strip()
        path = _find_dir(dirname) or _resolve_dest(dirname)
        if not os.path.isdir(path):
            return {"success": False, "error": f"Folder '{dirname}' not found."}
        if _is_protected(path):
            return {"success": False,
                    "error": f"Blocked: '{path}' is a protected system folder."}
        try:
            shutil.rmtree(path)
            return {"success": True, "result": f"Deleted folder `{path}`"}
        except Exception as e:
            return {"success": False, "error": f"delete folder failed: {e}"}

    # ── rename file or folder ────────────────────────────────────────────────
    if t == "rename_file":
        old_name, new_name = g[0].strip(), g[1].strip()
        old_path = _find_any(old_name) or _resolve_default_path(old_name)
        if not os.path.exists(old_path):
            return {"success": False, "error": f"'{old_name}' not found."}
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        try:
            os.rename(old_path, new_path)
            return {"success": True,
                    "result": f"Renamed:\n`{old_path}`\n→ `{new_path}`"}
        except Exception as e:
            return {"success": False, "error": f"rename failed: {e}"}

    # ── copy file or folder ──────────────────────────────────────────────────
    if t == "copy_file":
        src_name, dest_str = g[0].strip(), g[1].strip()
        src_path  = _find_any(src_name) or _resolve_default_path(src_name)
        if not os.path.exists(src_path):
            return {"success": False, "error": f"'{src_name}' not found."}
        dest_dir  = _resolve_dest(dest_str)
        dest_path = os.path.join(dest_dir, os.path.basename(src_path))
        try:
            os.makedirs(dest_dir, exist_ok=True)
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dest_path)
            return {"success": True,
                    "result": f"Copied to `{dest_path}`",
                    "verified_path": dest_path}
        except Exception as e:
            return {"success": False, "error": f"copy failed: {e}"}

    # ── move file or folder ───────────────────────────────────────────────────
    if t == "move_file":
        src_name, dest_str = g[0].strip(), g[1].strip()
        src_path  = _find_any(src_name) or _resolve_default_path(src_name)
        if not os.path.exists(src_path):
            return {"success": False, "error": f"'{src_name}' not found."}
        if _is_protected(src_path):
            return {"success": False,
                    "error": f"Blocked: '{src_path}' is in a protected location."}
        dest_dir  = _resolve_dest(dest_str)
        dest_path = os.path.join(dest_dir, os.path.basename(src_path))
        try:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(src_path, dest_path)
            return {"success": True,
                    "result": f"Moved to `{dest_path}`",
                    "verified_path": dest_path}
        except Exception as e:
            return {"success": False, "error": f"move failed: {e}"}

    # ── run script ────────────────────────────────────────────────────────────
    if t == "run_script":
        import subprocess, sys as _sys
        filename = g[0].strip()
        path = _find(filename) or _resolve_default_path(filename)
        if not os.path.exists(path):
            return {"success": False, "error": f"'{filename}' not found."}
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".py":
                proc = subprocess.run(
                    [_sys.executable, path],
                    capture_output=True, text=True, timeout=60
                )
            elif ext in (".bat", ".sh"):
                proc = subprocess.run(
                    path, capture_output=True, text=True,
                    timeout=60, shell=True
                )
            elif ext == ".ps1":
                proc = subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", path],
                    capture_output=True, text=True, timeout=60
                )
            else:
                return {"success": False,
                        "error": f"Unsupported script type: {ext}"}
            output = (proc.stdout + proc.stderr).strip()[:3000] or "(no output)"
            return {
                "success": proc.returncode == 0,
                "result":  f"Ran `{path}` (exit {proc.returncode}):\n```\n{output}\n```",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Script timed out after 60s."}
        except Exception as e:
            return {"success": False, "error": f"run failed: {e}"}

    # ── zip / compress ────────────────────────────────────────────────────────
    if t == "zip_item":
        import zipfile
        target_name = g[0].strip()
        output_name = (g[1].strip() if g[1] else target_name)
        if not output_name.endswith(".zip"):
            output_name += ".zip"
        target_path = _find_any(target_name) or _resolve_default_path(target_name)
        if not os.path.exists(target_path):
            return {"success": False, "error": f"'{target_name}' not found."}
        output_path = _resolve_default_path(output_name)
        try:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if os.path.isdir(target_path):
                    for root, _, fnames in os.walk(target_path):
                        for fname in fnames:
                            fp = os.path.join(root, fname)
                            zf.write(fp, os.path.relpath(
                                fp, os.path.dirname(target_path)))
                else:
                    zf.write(target_path, os.path.basename(target_path))
            size = os.path.getsize(output_path)
            return {"success": True,
                    "result": f"Compressed to `{output_path}` ({size:,} bytes)",
                    "verified_path": output_path}
        except Exception as e:
            return {"success": False, "error": f"zip failed: {e}"}

    # ── list directory ────────────────────────────────────────────────────────
    if t == "list_dir":
        target  = g[0].strip()
        dirpath = _find_dir(target) or _resolve_dest(target)
        if not os.path.isdir(dirpath):
            # Maybe it's a known shorthand not in shortcuts
            dirpath = os.path.expandvars(os.path.expanduser(target))
        if not os.path.isdir(dirpath):
            return {"success": False,
                    "error": f"'{target}' is not a directory or wasn't found."}
        try:
            entries = os.listdir(dirpath)
            _dirs  = sorted([e for e in entries
                              if os.path.isdir(os.path.join(dirpath, e))])
            _files = sorted([e for e in entries
                              if os.path.isfile(os.path.join(dirpath, e))])
            out = f"**{dirpath}**\n{len(_dirs)} folders · {len(_files)} files\n\n"
            if _dirs:
                out += "📁 Folders:\n" + "\n".join(f"  {d}" for d in _dirs[:30])
                if len(_dirs) > 30:
                    out += f"\n  … and {len(_dirs)-30} more"
                out += "\n\n"
            if _files:
                out += "📄 Files:\n" + "\n".join(f"  {f}" for f in _files[:50])
                if len(_files) > 50:
                    out += f"\n  … and {len(_files)-50} more"
            return {"success": True, "result": out}
        except Exception as e:
            return {"success": False, "error": f"list failed: {e}"}

    # ── time / date ───────────────────────────────────────────────────────────
    if t == "get_time":
        import datetime as _dt
        now = _dt.datetime.now()
        return {"success": True, "result": f"It's {now.strftime('%I:%M %p')} — {now.strftime('%A, %d %B %Y')}"}

    if t == "get_date":
        import datetime as _dt
        today = _dt.datetime.now()
        return {"success": True, "result": f"Today is {today.strftime('%A, %d %B %Y')}"}

    # ── screenshot ────────────────────────────────────────────────────────────
    if t == "take_screenshot":
        return execute_action("screenshot", {})

    # ── volume ────────────────────────────────────────────────────────────────
    if t == "volume_up":
        from computer_control import press_key as _pk
        for _ in range(5):
            _pk("volumeup")
        return {"success": True, "result": "Volume up."}

    if t == "volume_down":
        from computer_control import press_key as _pk
        for _ in range(5):
            _pk("volumedown")
        return {"success": True, "result": "Volume down."}

    if t == "volume_mute":
        from computer_control import press_key as _pk
        _pk("volumemute")
        return {"success": True, "result": "Muted/unmuted."}

    # ── media controls ────────────────────────────────────────────────────────
    if t == "media_pause":
        from computer_control import hotkey as _hk
        _hk("space")
        return {"success": True, "result": "Paused."}

    if t == "media_play":
        from computer_control import press_key as _pk
        _pk("space")
        return {"success": True, "result": "Playing."}

    if t == "media_next":
        from computer_control import press_key as _pk
        _pk("nexttrack")
        return {"success": True, "result": "Next track."}

    if t == "media_prev":
        from computer_control import press_key as _pk
        _pk("prevtrack")
        return {"success": True, "result": "Previous track."}

    # ── window control ────────────────────────────────────────────────────────
    if t == "minimize_window":
        from computer_control import hotkey as _hk
        _hk("win", "down")
        return {"success": True, "result": "Window minimized."}

    if t == "maximize_window":
        from computer_control import hotkey as _hk
        _hk("win", "up")
        return {"success": True, "result": "Window maximized."}

    if t == "close_window":
        from computer_control import hotkey as _hk
        _hk("alt", "f4")
        return {"success": True, "result": "Window closed."}

    # ── key presses ───────────────────────────────────────────────────────────
    if t == "press_escape":
        from computer_control import press_key as _pk
        _pk("escape")
        return {"success": True, "result": "Pressed Escape."}

    if t == "press_enter":
        from computer_control import press_key as _pk
        _pk("enter")
        return {"success": True, "result": "Pressed Enter."}

    if t == "press_tab":
        from computer_control import press_key as _pk
        _pk("tab")
        return {"success": True, "result": "Pressed Tab."}

    if t == "press_backspace":
        from computer_control import press_key as _pk
        _pk("backspace")
        return {"success": True, "result": "Pressed Backspace."}

    if t == "press_delete":
        from computer_control import press_key as _pk
        _pk("delete")
        return {"success": True, "result": "Pressed Delete."}

    if t == "press_space":
        from computer_control import press_key as _pk
        _pk("space")
        return {"success": True, "result": "Pressed Space."}

    if t == "press_key_name":
        from computer_control import press_key as _pk
        key_name = (g[0] or "").strip().lower()
        if not key_name:
            return {"success": False, "error": "No key specified."}
        _pk(key_name)
        return {"success": True, "result": f"Pressed {key_name}."}

    # ── scroll ────────────────────────────────────────────────────────────────
    if t == "scroll_down":
        from computer_control import scroll as _scroll
        n = int(g[0]) if g and g[0] else 5
        _scroll("down", n)
        return {"success": True, "result": f"Scrolled down {n}."}

    if t == "scroll_up":
        from computer_control import scroll as _scroll
        n = int(g[0]) if g and g[0] else 5
        _scroll("up", n)
        return {"success": True, "result": f"Scrolled up {n}."}

    # ── type text ─────────────────────────────────────────────────────────────
    if t == "type_text_cmd":
        text = (g[0] or "").strip()
        if not text:
            return {"success": False, "error": "No text to type."}
        return execute_action("type_text", {"text": text})

    # ── media ──────────────────────────────────────────────────────────────────
    if t == "play_media_on":
        import urllib.parse
        query, browser = g[0].strip(), g[1].strip()
        url = ("https://www.youtube.com/results?search_query="
               + urllib.parse.quote(query))
        return execute_action("open_url", {"url": url, "browser": browser})

    if t == "play_media":
        import urllib.parse
        url = ("https://www.youtube.com/results?search_query="
               + urllib.parse.quote(g[0].strip()))
        return execute_action("open_url", {"url": url})

    # ── search ─────────────────────────────────────────────────────────────────
    if t == "open_and_search":
        # groups: (site, query) — inverted vs search_on
        return execute_action("search_on_site",
                              {"query": g[1].strip(), "site": g[0].strip()})

    if t == "search_on":
        return execute_action("search_on_site",
                              {"query": g[0].strip(), "site": g[1].strip()})

    if t == "search_web":
        return execute_action("search_web", {"query": g[0].strip()})

    return {"success": False, "error": f"Unknown intent type: {t}"}
