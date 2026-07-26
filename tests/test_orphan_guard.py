"""Unit tests for the orphan detector itself (see tests/test_no_new_orphans.py
for the gate that actually enforces it against this repo)."""
import orphan_guard as og


def _write(tmp_path, name, body=""):
    p = tmp_path / f"{name}.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_module_imported_statically_is_not_an_orphan(tmp_path):
    _write(tmp_path, "leaf", "VALUE = 1\n")
    _write(tmp_path, "root", "import leaf\n")
    assert "leaf" not in og.find_orphans(root=str(tmp_path))


def test_module_imported_via_from_is_not_an_orphan(tmp_path):
    _write(tmp_path, "leaf", "def f(): pass\n")
    _write(tmp_path, "root", "from leaf import f\n")
    assert "leaf" not in og.find_orphans(root=str(tmp_path))


def test_module_nobody_imports_is_an_orphan(tmp_path):
    _write(tmp_path, "leaf", "VALUE = 1\n")
    _write(tmp_path, "root", "x = 1\n")
    assert "leaf" in og.find_orphans(root=str(tmp_path))


def test_import_inside_a_function_counts(tmp_path):
    # Phase hooks import lazily inside the stage function; that IS wiring.
    _write(tmp_path, "leaf", "def f(): pass\n")
    _write(tmp_path, "root", "def go():\n    import leaf\n    return leaf.f()\n")
    assert "leaf" not in og.find_orphans(root=str(tmp_path))


# ── the blind spot wiring_audit.py has ──────────────────────────────────────
def test_dynamic_string_import_counts_as_wired(tmp_path):
    # ultimate_routes.py loads real modules via __import__("name"); an AST walk
    # over Import nodes cannot see that, and reported them as false orphans.
    _write(tmp_path, "leaf", "def f(): pass\n")
    _write(tmp_path, "root", 'mod = __import__("leaf")\n')
    assert "leaf" not in og.find_orphans(root=str(tmp_path))


def test_indirect_string_loader_counts_as_wired(tmp_path):
    _write(tmp_path, "leaf", "def f(): pass\n")
    _write(tmp_path, "root", 'leaf = _safe_import("leaf")\n')
    assert "leaf" not in og.find_orphans(root=str(tmp_path))


def test_a_module_referencing_only_itself_is_still_an_orphan(tmp_path):
    _write(tmp_path, "leaf", 'NAME = "leaf"\nimport leaf\n')
    _write(tmp_path, "root", "x = 1\n")
    assert "leaf" in og.find_orphans(root=str(tmp_path))


def test_unparseable_file_does_not_crash_the_scan(tmp_path):
    _write(tmp_path, "broken", "this is not python (((\n")
    _write(tmp_path, "leaf", "VALUE = 1\n")
    orphans = og.find_orphans(root=str(tmp_path))
    assert "leaf" in orphans  # scan completed rather than raising


def test_tests_directory_does_not_count_as_production_wiring(tmp_path):
    # A module imported ONLY by its own test file is exactly the bug we're
    # guarding against — that must still read as an orphan.
    _write(tmp_path, "leaf", "def f(): pass\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_leaf.py").write_text("import leaf\n", encoding="utf-8")
    assert "leaf" in og.find_orphans(root=str(tmp_path))
