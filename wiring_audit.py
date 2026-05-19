"""Wiring audit — find modules and functions that exist but aren't wired in.

For each top-level .py module:
- Is it imported anywhere?
- How many times is it imported?
- For each top-level def/class, is it referenced anywhere outside its own file?

Distinguishes:
- ORPHAN: module never imported by anyone
- WEAK: module imported by 1 file (often the registration site)
- INNER-UNUSED: module imported, but specific top-level callables defined inside it have zero external references
"""
import ast, os, glob, json, re, sys
sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_FILES = sorted(glob.glob(os.path.join(ROOT, "*.py")))
PY_NAMES = {os.path.splitext(os.path.basename(p))[0] for p in PY_FILES}
EXCLUDE = {"test", "test_groq", "test_play", "test_stream", "test_youtube",
           "ultron_test", "self_modify_log", "app_additions"}  # known test/aux files

# 1) Build inter-module import graph
imports_by_file = {}   # file -> set of imported local module names
importers_of    = {}   # module name -> set of files that import it

def parse_imports(filepath):
    try:
        src = open(filepath, encoding="utf-8", errors="replace").read()
        tree = ast.parse(src, filename=filepath)
    except Exception:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names & PY_NAMES   # only local

for f in PY_FILES:
    name = os.path.splitext(os.path.basename(f))[0]
    imports_by_file[name] = parse_imports(f)
    for imp in imports_by_file[name]:
        importers_of.setdefault(imp, set()).add(name)

# 2) Collect top-level defs / classes per module + external references
defs_by_module = {}   # mod -> [name]
all_source = {}
for f in PY_FILES:
    name = os.path.splitext(os.path.basename(f))[0]
    try:
        src = open(f, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    all_source[name] = src
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    funcs = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            funcs.append(node.name)
    defs_by_module[name] = funcs

# external-reference count = number of files (other than the def's own) that mention the name
external_refs = {}   # (mod, def) -> [referencing_files]
for mod, defs in defs_by_module.items():
    for d in defs:
        if d.startswith("_") or d in ("main", "init", "run"):
            continue
        # Search the rest of the codebase for the symbol
        pat = re.compile(rf"\b{re.escape(d)}\b")
        hits = []
        for other_mod, src in all_source.items():
            if other_mod == mod: continue
            if pat.search(src):
                hits.append(other_mod)
        external_refs[(mod, d)] = hits

# 3) Report
def status(mod):
    importers = importers_of.get(mod, set()) - {mod}
    return "ORPHAN" if not importers else f"imported_by={len(importers)}"

print("="*80)
print("ULTRON WIRING AUDIT")
print("="*80)

# Section A — modules never imported by any other local module
print("\n## A — Modules with NO local importers (potential orphans)\n")
orphans = []
for mod in sorted(PY_NAMES):
    if mod in EXCLUDE: continue
    imps = importers_of.get(mod, set())
    if not imps:
        orphans.append(mod)
        print(f"  {mod}")
print(f"\n  total orphans: {len(orphans)}")

# Section B — modules imported by exactly ONE other module
print("\n## B — Weak coupling (imported by exactly 1 file)\n")
weak = []
for mod in sorted(PY_NAMES):
    if mod in EXCLUDE: continue
    imps = importers_of.get(mod, set()) - {mod}
    if len(imps) == 1:
        importer = next(iter(imps))
        weak.append((mod, importer))
        print(f"  {mod:25s}  imported only by  {importer}")
print(f"\n  total weak: {len(weak)}")

# Section C — top-level functions defined but never referenced outside their own file
print("\n## C — Top-level functions/classes with ZERO external references\n")
zero_ref = []
for (mod, d), refs in sorted(external_refs.items()):
    if not refs:
        zero_ref.append((mod, d))
# Group by module
by_mod = {}
for mod, d in zero_ref:
    by_mod.setdefault(mod, []).append(d)
for mod in sorted(by_mod.keys()):
    if mod in EXCLUDE: continue
    items = by_mod[mod]
    # filter out: classes that ARE the module's public entry, common decorators, etc.
    if len(items) > 30:   # too noisy, skip
        print(f"  {mod}: {len(items)} unreferenced (skipping detail)")
        continue
    print(f"  {mod}:")
    for d in items[:25]:
        print(f"     - {d}")
print(f"\n  total unreferenced top-level defs: {len(zero_ref)}")

# Section D — modules that are imported, but check what role they play
print("\n## D — Heaviest connectors (most importers)\n")
heavy = sorted(((mod, len(imps - {mod})) for mod, imps in importers_of.items()), key=lambda x: -x[1])
for mod, n in heavy[:15]:
    print(f"  {mod:30s}  imported by {n} files")

# Section E — Flask blueprints / route counts
print("\n## E — Modules that register Flask routes / blueprints\n")
for f in PY_FILES:
    name = os.path.splitext(os.path.basename(f))[0]
    src = all_source.get(name, "")
    n_routes = len(re.findall(r"@\w+\.route\(", src))
    if n_routes:
        print(f"  {name:30s}  {n_routes} @route(s)")

# Save
out = {
    "orphans": orphans,
    "weak": weak,
    "unreferenced_defs_by_module": {m: by_mod[m] for m in by_mod if m not in EXCLUDE},
    "heavy_connectors": heavy[:15],
}
out_path = os.path.join(ROOT, "_test_workspace", "results", "session_2026_05_16_late", "wiring_audit.json")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w") as f:
    json.dump(out, f, indent=2, default=str)
print(f"\nWrote {out_path}")
