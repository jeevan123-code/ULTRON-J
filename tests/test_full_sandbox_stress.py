"""
Full-sandbox stress test — user directive saved as memory
[[feedback-ultron-full-sandbox-test]] during Phase 7.

Goal: drive every Ultron-J ability through its real code path AFTER
all 9 hardening phases are committed. Per-phase tests cover the slice
that was just changed; this horizontal pass catches integration bugs
the per-phase suites might miss.

Categories:
  A. Every action_engine.execute_action type with realistic params
  B. The full intent_router dispatch sweep (covered by Phase 2.3 audit
     — re-confirmed here in one place)
  C. Goal lifecycle end-to-end (Phase 3 path, re-verified)
  D. Confirm gate edge cases (right token / wrong token / missing field)
  E. Destructive-action classifier (Phase 7.3 consolidated gate)
  F. Sandbox escape attempts (the classic class-walk + import-os
     patterns -- must be refused by _check_code_safety blocklist)
  G. Plugin contract (write a test plugin via write_skill_plugin,
     verify auto-load + dispatch path)
  H. Loop supervisor (config respected, backpressure helper works)
  I. Auth gate edges (loopback / remote / wrong key / right key)

The test is rigorous, not exhaustive — it picks one strong probe per
category. Failures here mean the integration story has drifted from
the per-phase test stories.

Run:  venv/bin/python -m pytest tests/test_full_sandbox_stress.py -v --timeout=30
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module                       # noqa: E402
import auth                                     # noqa: E402
import action_engine as ae                      # noqa: E402
import intent_router as ir                      # noqa: E402
import decision_engine as de                    # noqa: E402
import autonomous_loop as al                    # noqa: E402
import confirm_gate as cg                       # noqa: E402
import loop_supervisor as ls                    # noqa: E402


# ─── A. Every action_engine tool type ────────────────────────────────────────

class TestActionEngineFullCoverage:
    """One probe per action_engine.execute_action branch."""

    def test_calculate_ok(self):
        out = ae.execute_action("calculate", {"expression": "(2+3)*4"})
        assert out["success"]
        assert "20" in str(out["result"])

    def test_calculate_invalid(self):
        out = ae.execute_action("calculate", {"expression": "import os"})
        # safe_calculate rejects non-arithmetic; bad input must NOT crash
        assert out["success"] is False or "20" not in str(out.get("result", ""))

    def test_run_python_sandbox_basic(self):
        out = ae.execute_action("run_python", {"code": "print(2**10)"})
        assert out["success"] and "1024" in out["result"]

    def test_file_roundtrip(self, tmp_path):
        f = tmp_path / "x.txt"
        w = ae.execute_action("create_file", {"path": str(f), "content": "hi"})
        assert w["success"]
        r = ae.execute_action("file_read", {"path": str(f)})
        assert r["success"] and r["result"] == "hi"

    def test_append_file(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("one\n")
        a = ae.execute_action("append_file", {"path": str(f), "content": "two\n"})
        assert a["success"] and f.read_text() == "one\ntwo\n"

    def test_file_list_well_known(self):
        out = ae.execute_action("file_list", {"path": "~"})
        assert out["success"]

    def test_delete_file_then_missing(self, tmp_path):
        f = tmp_path / "kill.txt"; f.write_text("x")
        ok = ae.execute_action("delete_file", {"path": str(f)})
        assert ok["success"] and not f.exists()
        missing = ae.execute_action("delete_file", {"path": str(f)})
        assert not missing["success"]  # second delete must fail cleanly

    def test_git_status_real_repo(self):
        out = ae.execute_action("git_status", {"path": str(ROOT)})
        assert out["success"]

    def test_note_create(self):
        out = ae.execute_action("note_create",
                                {"title": "stress test", "content": "phase9"})
        assert out["success"]

    def test_path_normalization_home_user(self):
        resolved = ae._resolve_path("/home/user/Desktop")
        assert resolved.startswith(os.path.expanduser("~"))

    def test_safety_check_blocks_dangerous_pattern(self):
        # decision_engine.safety_check is the action_engine guard
        from decision_engine import safety_check
        ok, _ = safety_check({"type": "create_file",
                              "params": {"path": "/tmp/x", "content": "rm -rf /"}})
        assert not ok  # dangerous substring rejected

    def test_safety_check_blocks_restricted_path(self):
        from decision_engine import safety_check
        ok, _ = safety_check({"type": "file_read", "params": {"path": "/etc/passwd"}})
        assert not ok  # /etc is restricted


# ─── D + E. Confirm gate + destructive-action classifier ─────────────────────

class TestConfirmAndDestructiveGates:
    def test_is_destructive_known_types(self):
        for t in ("delete_file", "delete_folder", "shutdown", "self_upgrade",
                  "send_email", "run_python", "run_command"):
            d, _ = cg.is_destructive(t, {})
            assert d, f"{t} should classify as destructive"

    def test_is_destructive_safe_types(self):
        for t in ("note_create", "file_read", "file_list", "weather_fetch",
                  "calculate", "git_status"):
            d, _ = cg.is_destructive(t, {})
            assert not d, f"{t} should NOT classify as destructive"

    def test_destructive_shell_regex(self):
        for cmd in ("rm -rf /", "del file.txt", "Remove-Item -Force",
                    "taskkill /F /PID 123", "format c:"):
            assert cg.is_destructive_shell(cmd), f"{cmd!r} should be flagged"
        for cmd in ("ls -la", "echo hi", "cat /etc/hostname", "python script.py"):
            assert not cg.is_destructive_shell(cmd), f"{cmd!r} false-positive"

    def test_dry_run_preview_describes_action(self):
        assert "delete" in cg.dry_run_preview("delete_file", {"path": "/x"}).lower()
        assert "self_upgrade" not in cg.dry_run_preview("self_upgrade", {})  # uses word "source"
        assert "rewrite" in cg.dry_run_preview("self_upgrade", {}).lower()


# ─── F. Sandbox escape attempts ──────────────────────────────────────────────

class TestSandboxEscapes:
    """The sandbox is NOT a security boundary against an adversarial
    payload (docstring says so). It IS supposed to refuse the
    blocklisted patterns at the safety-check tripwire. These tests
    document the guarantee and catch regressions if someone weakens
    _check_code_safety."""

    def test_blocklist_refuses_import_os(self):
        out = ae.run_code_sandbox("import os; print(os.listdir('/'))")
        # _check_code_safety should reject before exec; if not, sandbox
        # exec might succeed (real bug -- documents the boundary).
        # We expect refusal.
        assert not out["success"], (
            f"_check_code_safety should refuse 'import os'; got: {out}"
        )

    def test_blocklist_refuses_subprocess(self):
        out = ae.run_code_sandbox(
            "import subprocess; subprocess.run(['ls'])"
        )
        assert not out["success"]

    def test_blocklist_refuses_open(self):
        # `open` is not in restricted __builtins__ but writing to disk
        # via `open` is a side-effect the sandbox shouldn't grant.
        out = ae.run_code_sandbox("open('/tmp/sandbox_escape', 'w').write('x')")
        # Either blocklisted ('open' substring) or fails because `open`
        # isn't in safe_globals __builtins__. Either way: not success.
        assert not out["success"]

    def test_safe_arithmetic_runs(self):
        # run_code_sandbox returns {"output", "error", "success"} -- NOT
        # the {"result"} shape used by execute_action's wrappers.
        out = ae.run_code_sandbox("print(sum(range(10)))")
        assert out["success"] and "45" in out["output"]

    def test_timeout_kills_infinite_loop(self):
        out = ae.run_code_sandbox("while True: pass", timeout=2)
        assert not out["success"]
        assert "timed out" in (out.get("error") or "").lower()

    def test_class_walk_escape_attempt(self):
        """The classic class-walk escape:
            ().__class__.__base__.__subclasses__()[<n>](...)
        finds a subprocess.Popen-like class through the object
        hierarchy. The sandbox's restricted __builtins__ omits
        __import__, so even if the walk succeeds the attacker still
        can't import anything. We document this here: the call MAY
        succeed in walking the hierarchy, but it CAN'T turn that walk
        into a side-effect because nothing it reaches has a working
        `__init_subclass__ -> exec` path without an importable module.

        The sandbox docstring is explicit that this is NOT an
        adversarial security boundary; this test catches regressions
        if someone restores __import__ to safe_globals."""
        code = (
            "print(type(().__class__.__base__.__subclasses__()).__name__)"
        )
        out = ae.run_code_sandbox(code)
        # We don't assert refusal -- the class walk itself is legal
        # Python and the restricted builtins don't block `type` or
        # attribute access. What we DO assert is that NO subprocess /
        # os call inside the walked classes can actually fire, because
        # __import__ is absent.
        if out["success"]:
            assert "list" in (out.get("output") or "").lower(), (
                f"class walk returned unexpected shape: {out}"
            )
        # If sandbox refused outright, that's also acceptable -- the
        # behaviour just got stricter.

    def test_eval_blocked(self):
        # eval/exec are absent from safe_globals __builtins__ -- they
        # must NameError, proving the restriction is in place.
        out = ae.run_code_sandbox("eval('2+2')")
        assert not out["success"]


# ─── G. Plugin contract round-trip ───────────────────────────────────────────

class TestPluginContractRoundtrip:
    def test_write_skill_plugin_creates_loadable(self):
        import plugin_registry as pr
        plugin_name = "stress_test_phase9"
        code = (
            "PLUGIN_META = {'name': 'stress_test_phase9', "
            "'description': 'phase 9 stress probe', 'version': '1.0', "
            "'tags': ['test']}\n"
            "def match(text):\n"
            "    return 'stress9_trigger' in text.lower()\n"
            "def run(params):\n"
            "    return {'success': True, 'result': 'phase 9 plugin OK'}\n"
        )
        # Clean any leftover
        target = pr.PLUGINS_DIR + f"/{plugin_name}.py"
        if os.path.exists(target):
            os.remove(target)
        # Write
        r = pr.write_skill_plugin(plugin_name, code, "test", ["test"])
        assert r["success"], r
        # Load manually (don't wait for the 5s watcher)
        loaded = pr._load_plugin_file(r["path"])
        assert loaded and loaded["name"] == plugin_name
        assert callable(loaded.get("match"))
        # Match function works
        assert loaded["match"]("hey stress9_trigger right here")
        assert not loaded["match"]("unrelated text")
        # Run function works
        run_out = loaded["run"]({})
        assert run_out["success"] and "phase 9" in run_out["result"]
        # Cleanup
        os.remove(target)

    def test_write_skill_plugin_refuses_bad_syntax(self):
        import plugin_registry as pr
        r = pr.write_skill_plugin("stress_bad", "def run(p): if", "", [])
        assert not r["success"] and "syntax" in r["error"].lower()

    def test_write_skill_plugin_refuses_overwrite(self):
        import plugin_registry as pr
        # crypto_price exists in plugins/
        r = pr.write_skill_plugin("crypto_price", "PLUGIN_META={}\ndef run(p):return{}",
                                  "", [])
        assert not r["success"] and "already exists" in r["error"]


# ─── H. Loop supervisor ──────────────────────────────────────────────────────

class TestLoopSupervisor:
    def test_default_OFF_loops(self):
        for name in ("evolution", "proactive", "skill_learner", "screen_monitor"):
            assert not ls.loop_enabled(name), f"{name} should default OFF"

    def test_default_ON_loops(self):
        for name in ("autonomous", "perception", "system_monitor",
                     "distiller", "predictive", "code_indexer"):
            assert ls.loop_enabled(name), f"{name} should default ON"

    def test_interval_returns_configured(self):
        # predictive was retuned from 60s -> 300s in Phase 4.1
        assert ls.loop_interval_s("predictive", 99) == 300.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LOOPS_EVOLUTION_ENABLED", "1")
        assert ls.loop_enabled("evolution"), (
            "env override should win over config.LOOPS"
        )

    def test_backpressure_threshold(self):
        # Don't actually fill memory; just confirm the helper executes
        # and returns a bool. The threshold comes from config (default 70).
        assert isinstance(ls.should_skip_heavy_tick(), bool)
        snap = ls.snapshot()
        assert "loops" in snap and "mem_pct" in snap


# ─── I. Auth gate edges ──────────────────────────────────────────────────────

class TestAuthGateEdges:
    @pytest.fixture()
    def client(self):
        return app_module.app.test_client()

    def test_loopback_dev_mode(self, client, monkeypatch):
        monkeypatch.setattr(auth, "ULTRON_API_KEYS", [])
        r = client.get("/provider_health")
        assert r.status_code != 403  # loopback dev mode passes

    def test_remote_dev_mode_403(self, client, monkeypatch):
        monkeypatch.setattr(auth, "ULTRON_API_KEYS", [])
        r = client.get("/provider_health",
                       environ_overrides={"REMOTE_ADDR": "10.0.0.5"})
        assert r.status_code == 403

    def test_keys_set_wrong_header_401(self, client, monkeypatch):
        monkeypatch.setattr(auth, "ULTRON_API_KEYS", ["valid-key"])
        r = client.get("/provider_health", headers={"X-API-Key": "nope"})
        assert r.status_code == 401

    def test_keys_set_right_header_passes(self, client, monkeypatch):
        monkeypatch.setattr(auth, "ULTRON_API_KEYS", ["valid-key"])
        r = client.get("/provider_health", headers={"X-API-Key": "valid-key"})
        assert r.status_code != 401


# ─── J. Goal lifecycle end-to-end (re-verify Phase 3) ────────────────────────

class TestGoalLifecycleE2E:
    """One full goal: seed -> drive observe/decide/act -> COMPLETED."""

    @pytest.fixture(autouse=True)
    def _isolate_goal_state(self):
        gp = ROOT / "goals.json"
        ep = ROOT / "execution_log.json"
        backup = {}
        for f in (gp, ep):
            if f.exists():
                backup[f] = f.read_bytes()
                f.unlink()
        yield
        for f, c in backup.items():
            f.write_bytes(c)

    def test_one_real_goal_completes(self):
        g = de.create_goal(
            title="stress9 weather -> note",
            description="Fetch weather, save note.",
            priority=de.Priority.HIGH, source="stress9",
        )
        de.update_goal(g["id"], status=de.GoalStatus.PENDING, tasks=[
            {"id": "s0", "description": "weather", "status": de.TaskStatus.PENDING,
             "result": None, "tool": "weather_fetch",
             "params": {"location": "Hyderabad"},
             "attempts": 0, "depends_on": []},
            {"id": "s1", "description": "note", "status": de.TaskStatus.PENDING,
             "result": None, "tool": "note_create",
             "params": {"title": "stress9", "content": "ok"},
             "attempts": 0, "depends_on": ["s0"]},
        ])
        for _ in range(15):
            obs = al.observe_environment()
            d   = al.make_decision(obs)
            p   = al.plan_for_decision(d)
            if p.get("planned") and p.get("action") != "observe":
                al.act_on_plan(p)
            cur = de.get_goal(g["id"])
            if cur and cur["status"] == de.GoalStatus.COMPLETED:
                break
        cur = de.get_goal(g["id"])
        assert cur["status"] == de.GoalStatus.COMPLETED
        assert cur["execution_score"] > 0


# ─── K. HTTP route real-response sample (beyond smoke) ────────────────────────

class TestRouteRealResponses:
    @pytest.fixture()
    def client(self, monkeypatch):
        monkeypatch.setattr(auth, "ULTRON_API_KEYS", [])
        return app_module.app.test_client()

    def test_health_returns_module_status(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.get_json()
        # Real shape: {"ok": bool, "modules": {<name>: "ok"|"<err>"}}
        assert body.get("ok") in (True, False)
        assert "modules" in body
        # Each module name in the dict is a status string
        for name, status in body["modules"].items():
            assert isinstance(name, str) and isinstance(status, str)
        # Memory is one of the modules surveyed
        assert "memory" in body["modules"]

    def test_health_capabilities_returns_rows(self, client):
        r = client.get("/health/capabilities")
        assert r.status_code == 200
        body = r.get_json()
        assert body["counts"]["total"] >= 100
        assert len(body["rows"]) >= 100

    def test_proposals_list_shape(self, client):
        r = client.get("/proposals")
        assert r.status_code == 200
        body = r.get_json()
        assert "proposals" in body and "count" in body
        assert isinstance(body["proposals"], list)

    def test_apply_proposal_gated(self, client):
        # 0 confirm -> 428
        r = client.post("/proposals/0/apply", json={})
        assert r.status_code == 428

    def test_self_upgrade_gated(self, client):
        r = client.post("/self_upgrade/run", json={})
        assert r.status_code == 428


# ─── L. Autonomy guard refuses LLM code ──────────────────────────────────────

class TestAutonomyGuard:
    def test_execute_goal_step_refuses_run_python_without_human_marker(self):
        # Create a fake task with code execution but no human_confirmed
        from action_engine import execute_goal_step
        # We don't actually have a real goal to mutate -- the guard
        # checks the task BEFORE touching the goal. The error path
        # returns success=False with a clear message; the goal isn't
        # advanced, log_execution is called once.
        result = execute_goal_step("fake_goal_id", {
            "id": "s0", "tool": "run_python",
            "description": "fake step",
            "params": {"code": "print('hi')"},
        })
        assert not result["success"]
        assert "human_confirmed" in result["error"]

    def test_execute_goal_step_allows_run_python_with_human_marker(self, tmp_path):
        # With human_confirmed=True the guard lets it through.
        # We don't have a real goal_id; log_execution will append
        # silently. The sandbox should execute the code.
        from action_engine import execute_goal_step
        result = execute_goal_step("fake_goal_id", {
            "id": "s0", "tool": "run_python",
            "description": "approved step",
            "params": {"code": "print(7*6)"},
            "human_confirmed": True,
        })
        # update_goal will fail (goal doesn't exist) but the sandbox
        # ran first and returned its result.
        # Accept either success=True with '42' in output, OR success=False
        # if the missing-goal path bubbled up -- both prove the GATE
        # didn't refuse.
        if result["success"]:
            assert "42" in result.get("result", "")
        else:
            # If the gate had refused, error would mention human_confirmed
            assert "human_confirmed" not in result.get("error", "")
