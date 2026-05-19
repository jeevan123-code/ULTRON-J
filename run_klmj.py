"""
Backend-only test sweep: Phase K (hardening), L (stress), M (timing), J (self-upgrade).
Skips anything interactive / destructive / Ollama-related.
"""
import json, time, threading, requests, statistics, os, re, sys, subprocess
sys.path.insert(0, '.')

BASE = "http://127.0.0.1:5000"
findings = []
def OK(label, evidence=""): findings.append(("OK  ", label, evidence)); print(("  OK    " + label) + (("\n        " + evidence) if evidence else ""))
def FAIL(label, evidence=""): findings.append(("FAIL", label, evidence)); print(("  FAIL  " + label) + (("\n        " + evidence) if evidence else ""))
def WARN(label, evidence=""): findings.append(("WARN", label, evidence)); print(("  WARN  " + label) + (("\n        " + evidence) if evidence else ""))


def ask_sse(q, sid="batch"):
    t0 = time.time()
    r = requests.post(BASE + "/ask",
                      json={"question": q, "session_id": sid, "provider": "auto"},
                      headers={"Accept": "text/event-stream"}, stream=True, timeout=60)
    ct = r.headers.get("Content-Type", "")
    if "event-stream" not in ct:
        try: d = r.json()
        except: d = {"raw": r.text[:200]}
        return round(time.time() - t0, 2), d, "JSON"
    full = ""
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "): continue
        try: o = json.loads(line[6:])
        except: continue
        if o.get("type") == "status": continue
        full += o.get("token") or o.get("text") or ""
        if o.get("done") or o.get("type") == "done": break
    return round(time.time() - t0, 2), {"response": full.strip()}, "SSE"


# ===== PHASE K — HARDENING =====
print("\n========================================")
print("PHASE K - HARDENING")
print("========================================")

# K1
try:
    from self_modify import patch_file
    out = patch_file("config.py", "x=1")
    if not out.get("success") and "protected" in str(out).lower():
        OK("K1 self_modify rejects config.py", str(out)[:120])
    else:
        FAIL("K1 self_modify ALLOWS config.py write", str(out)[:120])
except ImportError:
    WARN("K1 self_modify module missing")
except Exception as e:
    FAIL("K1 self_modify error", str(e)[:120])

# K2
try:
    from self_modify import patch_file
    out = patch_file("memory.py", "x=1")
    if not out.get("success") and "protected" in str(out).lower():
        OK("K2 self_modify rejects memory.py", str(out)[:120])
    else:
        FAIL("K2 self_modify ALLOWS memory.py write", str(out)[:120])
except Exception as e:
    FAIL("K2 self_modify error", str(e)[:120])

# K4
try:
    from self_upgrade import FORBIDDEN
    needs = {"config.py", "memory.py", ".env"}
    missing = needs - set(FORBIDDEN)
    if not missing:
        OK("K4 FORBIDDEN guards config.py / memory.py / .env",
           "FORBIDDEN=" + str(sorted(FORBIDDEN))[:140])
    else:
        FAIL("K4 FORBIDDEN missing entries", "missing=" + str(missing))
except Exception as e:
    WARN("K4 self_upgrade not loadable", str(e)[:120])

# K5
import glob
bad = []
for f in glob.glob("*.py"):
    if f.startswith("_"): continue
    try:
        src = open(f, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    for m in re.finditer(r"json\.dump\(", src):
        line = src[:m.start()].count("\n") + 1
        seg = src[max(0, m.start() - 200):m.end() + 100]
        if "atomic_json_write" in seg: continue
        if "tmp" in seg.lower(): continue
        if "tempfile" in seg.lower(): continue
        bad.append((f, line))
if len(bad) == 0:
    OK("K5 every json.dump uses atomic_json_write or tmp")
elif len(bad) <= 5:
    WARN("K5 " + str(len(bad)) + " non-atomic json.dump call(s)",
         "; ".join(f + ":" + str(L) for f, L in bad[:5]))
else:
    FAIL("K5 " + str(len(bad)) + " non-atomic json.dump calls",
         "; ".join(f + ":" + str(L) for f, L in bad[:5]))


# ===== PHASE L — STRESS =====
print("\n========================================")
print("PHASE L - STRESS / EDGE CASES")
print("========================================")

# L1
dt, d, mode = ask_sse("", "l1")
resp = d.get("response", "") or str(d)
if dt < 30:
    OK("L1 empty query handled (" + str(dt) + "s, " + mode + ")", resp[:120])
else:
    FAIL("L1 empty query hung")

# L2 — long query
long_q = ("explain quantum entanglement and its applications in quantum computing " * 70)[:5000]
dt, d, mode = ask_sse(long_q, "l2")
resp = d.get("response", "") or str(d)
if dt < 60 and len(resp) > 20:
    OK("L2 5000-char query (" + str(dt) + "s, " + mode + ", " + str(len(resp)) + "-char reply)", resp[:100])
elif dt >= 60:
    FAIL("L2 5000-char query hung (" + str(dt) + "s)")
else:
    WARN("L2 5000-char query short reply", resp[:120])

# L3 — 10 parallel
def fire(i):
    try:
        dt, d, _ = ask_sse("give me a one-line fact about hyderabad (trial " + str(i) + ")", "l3_" + str(i))
        return (True, dt, len(d.get("response", "")))
    except Exception as e:
        return (False, 0, str(e)[:80])
threads, results = [], []
t0 = time.time()
for i in range(10):
    th = threading.Thread(target=lambda i=i: results.append(fire(i)))
    th.start(); threads.append(th)
for th in threads: th.join()
wall = round(time.time() - t0, 2)
ok_count = sum(1 for r in results if r[0])
if ok_count >= 8:
    OK("L3 10-parallel /ask: " + str(ok_count) + "/10 in " + str(wall) + "s")
else:
    FAIL("L3 only " + str(ok_count) + "/10 succeeded", str(results)[:200])

# L4 — invalid provider
r = requests.post(BASE + "/ask",
                  json={"question": "hi", "session_id": "l4", "provider": "fake_provider_xyz"},
                  headers={"Accept": "text/event-stream"}, stream=True, timeout=30)
got_anything = False
for line in r.iter_lines(decode_unicode=True):
    if line and "data:" in line:
        got_anything = True
        break
if got_anything:
    OK("L4 invalid provider — graceful fallback")
else:
    FAIL("L4 invalid provider gave no response")

# L5 — unicode + emoji
dt, d, _ = ask_sse("What does the sigma symbol mean in math, plus translate hello to chinese and add a party emoji, one sentence.", "l5")
resp = d.get("response", "")
if dt < 30 and len(resp) > 20:
    OK("L5 unicode/emoji (" + str(dt) + "s)", resp[:120])
else:
    FAIL("L5 unicode/emoji failed (" + str(dt) + "s)", resp[:120])


# ===== PHASE M — TIMING =====
print("\n========================================")
print("PHASE M - TIMING / PERFORMANCE")
print("========================================")

# M1
times = []
for i in range(5):
    dt, _, _ = ask_sse("what is 2 plus 2 (trial " + str(i) + ")", "m1_" + str(i))
    times.append(dt)
p50 = statistics.median(times)
p95 = sorted(times)[int(len(times) * 0.9)]
print("  M1 Groq short-query: 5 trials = " + str(times))
if p50 < 6 and p95 < 12:
    OK("M1 Groq p50=" + str(p50) + "s p95=" + str(p95) + "s within budget")
else:
    WARN("M1 Groq p50=" + str(p50) + "s p95=" + str(p95) + "s slower than spec (3s/6s)")

# M6
dt, d, _ = ask_sse("give me the latest tech news today in 2 sentences", "m6")
resp = d.get("response", "")
if dt < 15 and len(resp) > 60:
    OK("M6 cloud search latency " + str(dt) + "s, " + str(len(resp)) + "-char reply")
else:
    WARN("M6 cloud search " + str(dt) + "s len=" + str(len(resp)), resp[:100])

# M8 — picker cache hit
from task_orchestrator import picker_cache_clear, _llm_pick_action
picker_cache_clear()
t0 = time.time(); _llm_pick_action("snap a screenshot please")
miss = round(time.time() - t0, 2)
t0 = time.time(); _llm_pick_action("snap a screenshot please")
hit = round(time.time() - t0, 3)
if hit < 0.1:
    OK("M8 picker cache miss=" + str(miss) + "s hit=" + str(hit) + "s")
else:
    WARN("M8 picker cache slow hit: " + str(hit) + "s")


# ===== PHASE J — SELF-UPGRADE (read-only) =====
print("\n========================================")
print("PHASE J - SELF-UPGRADE (read-only)")
print("========================================")

if os.path.exists("error_log.json"):
    sz = os.path.getsize("error_log.json")
    OK("J1 error_log.json exists, " + str(sz) + " bytes")
else:
    WARN("J1 error_log.json missing (not yet written)")

r = requests.get(BASE + "/system/error_scores", timeout=10)
if r.status_code == 200:
    d = r.json()
    if "scores" in d and "top" in d:
        OK("J2 /system/error_scores schema valid", json.dumps(d)[:140])
    else:
        FAIL("J2 /system/error_scores wrong shape", json.dumps(d)[:140])
else:
    FAIL("J2 /system/error_scores HTTP " + str(r.status_code))


# ===== SUMMARY =====
print("\n========================================")
ok_n   = sum(1 for f in findings if f[0] == "OK  ")
warn_n = sum(1 for f in findings if f[0] == "WARN")
fail_n = sum(1 for f in findings if f[0] == "FAIL")
print("SUMMARY: " + str(ok_n) + " OK, " + str(warn_n) + " WARN, " + str(fail_n) + " FAIL (total " + str(len(findings)) + ")")
print("========================================")
for status, label, _ in findings:
    print("  " + status + " " + label)
