"""Orphan guard — is every module in this project reachable from PRODUCTION?

`wiring_audit.py` answers this for humans. This module is the machine-checkable
version, enforced by tests/test_no_new_orphans.py, so a phase can never again be
recorded as "shipped" while nothing but its own test file imports it. That has
now happened twice: Phases 5b/5g in one cycle, Phases 18/19/20/21/23 in the next.

Two rules make the answer trustworthy:

1. `tests/` is NOT production. A module imported only by its own test file is
   precisely the failure we are guarding against, so test files are never
   counted as importers.
2. String-loaded modules ARE wired. `ultimate_routes.py` pulls real modules in
   through `_safe_import("evolution_loop")` -> `__import__(name)`. A static walk
   over Import nodes cannot see that, which is why the AST-only audit reported
   evolution_loop / skill_learner / tweak_engine as orphans when they are live.
   We therefore also count string literals that name a project module.

Rule 2 is deliberately generous: a false "wired" is a missed warning, but a
false "orphan" trains people to ignore the gate.
"""
import ast
import glob
import os
from typing import Dict, List, Optional, Set

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Modules that are SUPPOSED to have no importers, with the reason. Anything not
# listed here that becomes an orphan fails the build.
ALLOWED_ORPHANS: Dict[str, str] = {
    # Standalone entry points — run directly, never imported.
    "ultron_listener": "standalone always-on voice listener process",
    "wiring_audit": "human-facing audit script",
    "setup_integrations": "one-shot setup script",
    # Stray root-level test file, kept out of tests/ — pre-existing.
    "test_t17": "stray root-level test file (pre-existing debt)",
    # The four grandfathered orphans are gone — all were wired via
    # startup_wiring.py rather than retired, because each was the missing half
    # of a feature that already had consumers.
}

# Non-production noise at the repo root (ad-hoc scratch/test files).
_EXCLUDE = {"test", "test_groq", "test_play", "test_stream", "test_youtube",
            "ultron_test"}


def project_modules(root: Optional[str] = None) -> Set[str]:
    """Top-level module names living at the project root."""
    root = root or _BASE_DIR
    return {
        os.path.splitext(os.path.basename(p))[0]
        for p in glob.glob(os.path.join(root, "*.py"))
    }


# Callables that turn a string into a module. A bare string literal is NOT
# enough evidence — "app" and "memory" appear as ordinary strings all over the
# codebase and would mark half the tree as wired.
_DYNAMIC_IMPORTERS = {"__import__", "import_module", "_safe_import",
                      "safe_import", "_lazy_import", "lazy_import"}


def _callee_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _references(path: str, known: Set[str]) -> Set[str]:
    """Project modules this file references, statically OR via a string loader."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        tree = ast.parse(src, filename=path)
    except Exception:
        return set()  # an unparseable file simply contributes no edges

    found: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and _callee_name(node) in _DYNAMIC_IMPORTERS:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value.split(".")[0])
    return found & known


def find_orphans(root: Optional[str] = None) -> List[str]:
    """Project modules that no OTHER production module references."""
    root = root or _BASE_DIR
    known = project_modules(root)
    importers: Dict[str, Set[str]] = {}

    for path in sorted(glob.glob(os.path.join(root, "*.py"))):
        name = os.path.splitext(os.path.basename(path))[0]
        for ref in _references(path, known):
            if ref != name:  # self-reference is not wiring
                importers.setdefault(ref, set()).add(name)

    return sorted(m for m in known
                  if m not in _EXCLUDE and not importers.get(m))


def unexpected_orphans(root: Optional[str] = None) -> List[str]:
    """Orphans that are NOT on the documented allowlist. Must stay empty."""
    return [m for m in find_orphans(root) if m not in ALLOWED_ORPHANS]


def stale_allowlist_entries(root: Optional[str] = None) -> List[str]:
    """Allowlist entries that are no longer orphans — delete them."""
    orphans = set(find_orphans(root))
    return sorted(m for m in ALLOWED_ORPHANS
                  if m in project_modules(root) and m not in orphans)
