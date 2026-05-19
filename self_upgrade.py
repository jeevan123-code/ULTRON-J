"""
self_upgrade.py — True self-improvement using existing Groq/Gemini.
Replaces fragile claude_loop.py browser automation.

Pipeline: diagnose -> generate fix -> validate -> apply -> hot reload.
Auto-rollback on any failure.
"""
import importlib
import os
import re
import shutil
import subprocess
import sys
import datetime
import ast
from typing import Dict

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(_BASE_DIR, "self_upgrade_backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# Files we will NEVER auto-modify
FORBIDDEN = {
    "config.py", "memory.json", ".env", "ultron.db",
    "memory.py", "intelligence_core.py",
}


def _parse_traceback_files(tb_string: str) -> list:
    """Extract (filepath, lineno) pairs from a Python traceback string.
    Only returns files that exist inside the project directory."""
    if not tb_string:
        return []
    pattern = re.compile(r'File "([^"]+)", line (\d+)')
    found = []
    seen  = set()
    for match in pattern.finditer(tb_string):
        raw_path = match.group(1)
        lineno   = int(match.group(2))
        # Normalize and check it's inside our project
        try:
            abs_path = os.path.abspath(raw_path)
            if not abs_path.startswith(_BASE_DIR):
                continue
            if not os.path.exists(abs_path):
                continue
            key = (abs_path, lineno)
            if key not in seen:
                seen.add(key)
                found.append((abs_path, lineno))
        except Exception:
            continue
    return found


def _read_lines_around(filepath: str, lineno: int, context: int = 25) -> str:
    """Read ±context lines around a given line number from a file."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        start = max(0, lineno - context - 1)
        end   = min(len(all_lines), lineno + context)
        snippet = "".join(
            f"{i+1:4d}| {line}"
            for i, line in enumerate(all_lines[start:end], start=start)
        )
        rel = os.path.relpath(filepath, _BASE_DIR)
        return f"--- {rel} (around line {lineno}) ---\n{snippet}"
    except Exception:
        return ""


def _get_module_imports(filepath: str) -> list:
    """Return the names of locally-present modules imported by a .py file."""
    try:
        import ast as _ast
        source = open(filepath, encoding="utf-8", errors="replace").read()
        tree   = _ast.parse(source, filename=filepath)
        names  = []
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.Import,)):
                for alias in node.names:
                    names.append(alias.name.split(".")[0])
            elif isinstance(node, (_ast.ImportFrom,)):
                if node.module:
                    names.append(node.module.split(".")[0])
        # Only keep ones that are local files
        local = []
        for n in set(names):
            candidate = os.path.join(_BASE_DIR, f"{n}.py")
            if os.path.exists(candidate) and n not in FORBIDDEN:
                local.append(n)
        return local
    except Exception:
        return []


def diagnose() -> Dict:
    """
    Find the top failing module and build rich context for the LLM:
    - Primary module source
    - All traceback-referenced files with line-level context
    - One level of local imports from the failing module
    - Recent error messages
    """
    try:
        from error_tracker import (
            get_top_problem_module, get_module_scores, recent_errors,
        )
    except ImportError:
        return {"diagnosis": "error_tracker not available"}

    mod = get_top_problem_module()
    if not mod:
        return {"diagnosis": "no failures detected"}

    fpath = os.path.join(_BASE_DIR, f"{mod}.py")
    if not os.path.exists(fpath):
        return {"diagnosis": f"file not found: {fpath}"}
    if os.path.basename(fpath) in FORBIDDEN:
        return {"diagnosis": f"{mod} is forbidden from auto-modify"}

    with open(fpath, encoding="utf-8") as f:
        source = f.read()

    errs = recent_errors(mod, limit=15)

    # ── Collect traceback context ─────────────────────────────────────────────
    tb_context_parts = []
    tb_files_seen    = set()

    for err in errs:
        tb = err.get("traceback", "")
        if not tb:
            continue
        for abs_path, lineno in _parse_traceback_files(tb):
            key = (abs_path, lineno // 10)   # bucket lines to avoid duplicate near-context
            if key in tb_files_seen:
                continue
            tb_files_seen.add(key)
            snippet = _read_lines_around(abs_path, lineno, context=20)
            if snippet:
                tb_context_parts.append(snippet)
            if len(tb_context_parts) >= 6:   # cap — don't flood the prompt
                break
        if len(tb_context_parts) >= 6:
            break

    # ── One level of local imports ────────────────────────────────────────────
    import_context_parts = []
    local_imports = _get_module_imports(fpath)
    for imp_name in local_imports[:4]:   # max 4 imported files
        imp_path = os.path.join(_BASE_DIR, f"{imp_name}.py")
        try:
            imp_src = open(imp_path, encoding="utf-8").read()[:2000]
            import_context_parts.append(
                f"--- {imp_name}.py (imported by {mod}) — first 2000 chars ---\n{imp_src}"
            )
        except Exception:
            pass

    return {
        "module":           mod,
        "filepath":         fpath,
        "source":           source,
        "errors":           errs,
        "scores":           get_module_scores(),
        "traceback_context": "\n\n".join(tb_context_parts),
        "import_context":   "\n\n".join(import_context_parts),
    }


def _top_level_defs(source: str) -> set:
    """Return the set of top-level function and class names defined in source.
    Used to verify generate_fix() preserved the file's public API."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def _parse_stream_llm_output(stream) -> str:
    """Reduce stream_llm's output to a single text string.
    stream_llm yields SSE-formatted strings ('data: {"token": "..."}\\n\\n')
    plus a final 'data: {"_full": "..."}\\n\\n'. Some providers may yield
    dicts or plain strings directly. Handle every shape; ignore status
    hints. Without this parsing, raw SSE lines would be concatenated as
    the 'fix' — the root cause of action_engine.py being overwritten on
    2026-05-16."""
    import json as _json
    full = None
    tokens = []
    for chunk in stream:
        payload = None
        if isinstance(chunk, dict):
            payload = chunk
        elif isinstance(chunk, str):
            line = chunk.strip()
            if line.startswith("data:"):
                body = line[5:].strip()
                try:
                    payload = _json.loads(body)
                except _json.JSONDecodeError:
                    payload = None
            else:
                # Provider yielded plain text — treat as a token.
                tokens.append(chunk)
                continue
        if not isinstance(payload, dict):
            continue
        if "_full" in payload:
            full = payload["_full"]
        elif "token" in payload:
            tokens.append(payload["token"])
        # status / other payload types are ignored
    return full if full is not None else "".join(tokens)


def generate_fix(diagnosis: Dict) -> str | None:
    """Send to LLM with rich traceback-aware context. Returns new source or None."""
    if "errors" not in diagnosis:
        return None

    err_summary = "\n".join(
        f"- [{e.get('function', '?')}] {e.get('error', '?')}"
        for e in diagnosis["errors"][:10]
    )

    # Include traceback line context if available
    tb_section = ""
    if diagnosis.get("traceback_context"):
        tb_section = (
            "\n\nTRACEBACK LINE CONTEXT (exact lines where failures occurred):\n"
            + diagnosis["traceback_context"][:3000]
        )

    # Include import context if available
    import_section = ""
    if diagnosis.get("import_context"):
        import_section = (
            "\n\nLOCAL DEPENDENCIES (files imported by the failing module):\n"
            + diagnosis["import_context"][:2000]
        )

    prompt = (
        "You are fixing a Python module that has been failing in production.\n"
        f"Module: {diagnosis['module']}.py\n\n"
        f"Recent failures:\n{err_summary}"
        f"{tb_section}"
        f"{import_section}\n\n"
        f"Full current source of {diagnosis['module']}.py:\n"
        f"```python\n{diagnosis['source'][:8000]}\n```\n\n"
        "Return the COMPLETE corrected source code. "
        "No explanation, no markdown fences, just raw Python. "
        "Preserve all existing function signatures and public APIs. "
        "Fix only what is broken — do not refactor or add features."
    )
    try:
        from llm_engine import stream_llm
        code = _parse_stream_llm_output(
            stream_llm([{"role": "user", "content": prompt}], temperature=0.2)
        ).strip()
        # Strip code fences if model wrapped it anyway
        if code.startswith("```"):
            lines = code.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            code = "\n".join(lines)
        return code
    except Exception:
        return None


def validate(code: str, module_name: str, original_source: str = "") -> Dict:
    """Syntax check + public-API survival + import dry run in subprocess.

    The original implementation accepted any AST-parseable input, which let
    a stream of SSE lines (``data: {"token": "..."}``) pass — those parse
    as PEP 526 variable annotations, no SyntaxError raised. The
    public-API check below blocks that class of corruption: the new code
    must define every top-level function and class the old file defined,
    otherwise the candidate is rejected before it touches disk."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"ok": False, "error": f"syntax error: {e}"}

    if original_source:
        original_defs = _top_level_defs(original_source)
        new_defs      = _top_level_defs(code)
        missing       = original_defs - new_defs
        if missing:
            return {
                "ok": False,
                "error": f"missing top-level defs: {sorted(missing)[:8]}",
            }

    tmp_path = os.path.join(_BASE_DIR, f"_test_{module_name}.py")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        # Use real import semantics, not exec(), so side-effects of import-time
        # code (e.g. config loads) get the same path stack the production
        # module would.
        proc = subprocess.run(
            [sys.executable, "-c",
             f"import sys, importlib.util; "
             f"spec = importlib.util.spec_from_file_location("
             f"'_test_{module_name}', r'{tmp_path}'); "
             f"mod = importlib.util.module_from_spec(spec); "
             f"sys.path.insert(0, r'{_BASE_DIR}'); "
             f"spec.loader.exec_module(mod)"],
            capture_output=True, timeout=10, cwd=_BASE_DIR,
        )
        if proc.returncode != 0:
            return {"ok": False,
                    "error": f"import failed: {proc.stderr.decode()[:300]}"}
        return {"ok": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "import test timed out"}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def apply_fix(filepath: str, new_code: str) -> Dict:
    """Backup, write, hot-reload, auto-rollback on failure.

    After reload, the new module's callables are compared against the
    pre-write snapshot. If a previously-callable name is missing, the
    module body silently lost its API and we restore the backup. The
    in-process check complements ``validate``'s subprocess check —
    reload semantics differ enough from a fresh import that we need
    both gates."""
    name = os.path.basename(filepath)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUP_DIR, f"{name}.{ts}.bak")
    shutil.copy2(filepath, backup)
    mod_name = name[:-3]

    # Snapshot the live module's public callables before we touch the file.
    pre_callables = set()
    pre_mod = sys.modules.get(mod_name)
    if pre_mod is not None:
        pre_callables = {
            n for n in dir(pre_mod)
            if not n.startswith("_") and callable(getattr(pre_mod, n, None))
        }

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_code)
    try:
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            importlib.import_module(mod_name)

        post_mod = sys.modules.get(mod_name)
        post_callables = {
            n for n in dir(post_mod)
            if not n.startswith("_") and callable(getattr(post_mod, n, None))
        } if post_mod else set()
        missing = pre_callables - post_callables
        if missing:
            raise RuntimeError(f"lost public callables after reload: {sorted(missing)[:8]}")

        return {"success": True, "backup": backup}
    except Exception as e:
        shutil.copy2(backup, filepath)
        try:
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
        except Exception:
            pass
        return {
            "success": False,
            "error": str(e)[:200],
            "rolled_back": True,
            "backup": backup,
        }


def run_upgrade() -> Dict:
    """Full pipeline: diagnose -> generate -> validate -> apply."""
    diag = diagnose()
    if "module" not in diag:
        return diag
    fix = generate_fix(diag)
    if not fix:
        return {"success": False, "error": "fix generation failed"}
    val = validate(fix, diag["module"], original_source=diag.get("source", ""))
    if not val["ok"]:
        return {"success": False, "error": val["error"]}
    return apply_fix(diag["filepath"], fix)
