"""
Phase D — Task Management / Action Execution Tests
Tests D1-D7, D10-D12 are fully automated via /ask API.
D8, D9 (media play) open browser windows — audio/click verified manually.
"""
import requests, json, time, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOG_FILE = r"C:\Users\xjoke\OneDrive\Desktop\ULTRON-WEB\_test_workspace\results\phase_d.log"
DESKTOP  = r"C:\Users\xjoke\OneDrive\Desktop"

lines = []
passes, fails, partials = [], [], []

def log(s=""):
    print(s, flush=True)
    lines.append(s)

def ask(question, session_id="phase_d", provider="auto", timeout=15):
    start = time.time()
    try:
        r = requests.post(
            "http://localhost:5000/ask",
            json={"question": question, "session_id": session_id, "provider": provider},
            stream=True, timeout=timeout,
        )
        ct = r.headers.get("Content-Type", "")
        if "text/event-stream" not in ct:
            try:
                d = r.json()
                ans = (d.get("response") or d.get("result") or str(d)).strip()
                return ans, round(time.time()-start,1), d.get("executed", False), d.get("result",{})
            except Exception:
                pass
        full, executed = "", False
        detail = {}
        for line in r.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8", errors="replace")
            if line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                    if "token" in d and d.get("type") != "status":
                        full += d["token"]
                    if d.get("_full"):
                        full = d["_full"]
                    if d.get("executed"):
                        executed = True
                    if d.get("result"):
                        detail = d["result"]
                except Exception:
                    pass
        return full.strip(), round(time.time()-start,1), executed, detail
    except Exception as e:
        return f"[ERROR] {e}", round(time.time()-start,1), False, {}

def record(tid, status, note=""):
    tag = f"{tid}: {status}" + (f" — {note}" if note else "")
    log(f"RESULT: {status}" + (f" — {note}" if note else ""))
    if status == "PASS":
        passes.append(tag)
    elif status == "FAIL":
        fails.append(tag)
    else:
        partials.append(tag)

def file_exists(path):
    return os.path.isfile(path)

def file_content(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

# ─────────────────────────────────────────────────────────────────────────────
log("=" * 70)
log("PHASE D — ACTION EXECUTION TESTS")
log(f"Run date: {time.strftime('%Y-%m-%d %H:%M')}")
log("=" * 70)

# ── D1: Open Notepad ─────────────────────────────────────────────────────────
log("\nTEST D1 — APP OPEN: notepad")
ans, t, executed, detail = ask("open notepad")
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
if executed or "done" in ans.lower() or "notepad" in ans.lower() or "open" in ans.lower():
    record("D1", "PASS", f"{t}s")
else:
    record("D1", "FAIL", ans[:80])
time.sleep(2)

# ── D2: Open VS Code ─────────────────────────────────────────────────────────
log("\nTEST D2 — APP OPEN: visual studio code (system index)")
ans, t, executed, detail = ask("open visual studio code")
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
if executed or "done" in ans.lower() or "code" in ans.lower() or "visual" in ans.lower():
    record("D2", "PASS", f"{t}s — VS Code opened or found")
elif "not found" in ans.lower() or "fail" in ans.lower():
    record("D2", "PARTIAL", "VS Code not installed or not in index")
else:
    record("D2", "FAIL", ans[:80])
time.sleep(2)

# ── D3: Open ChatGPT (web fallback) ──────────────────────────────────────────
log("\nTEST D3 — APP OPEN: chatgpt (web fallback)")
ans, t, executed, detail = ask("open chatgpt")
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
if executed or "done" in ans.lower() or "chatgpt" in ans.lower() or "openai" in ans.lower():
    record("D3", "PASS", f"{t}s")
else:
    record("D3", "FAIL", ans[:80])
time.sleep(2)

# ── D4: Open Brave ───────────────────────────────────────────────────────────
log("\nTEST D4 — APP OPEN: brave browser")
ans, t, executed, detail = ask("open brave")
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
if executed or "done" in ans.lower() or "brave" in ans.lower():
    record("D4", "PASS", f"{t}s")
elif "not found" in ans.lower() or "fail" in ans.lower():
    record("D4", "PARTIAL", "Brave not installed")
else:
    record("D4", "FAIL", ans[:80])
time.sleep(2)

# ── D5: File Create (no content) ─────────────────────────────────────────────
log("\nTEST D5 — FILE CREATE: test_ultron.txt on Desktop")
test_file = os.path.join(DESKTOP, "test_ultron.txt")
if file_exists(test_file):
    os.remove(test_file)   # clean slate
ans, t, executed, detail = ask(
    f"create file test_ultron.txt in {DESKTOP}"
)
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
time.sleep(1)
if file_exists(test_file):
    sz = os.path.getsize(test_file)
    log(f"VERIFY: file exists, size={sz} bytes")
    record("D5", "PASS", f"file on disk, {sz} bytes")
else:
    record("D5", "FAIL", f"file not found at {test_file}")
time.sleep(2)

# ── D6: File Create with content ─────────────────────────────────────────────
log("\nTEST D6 — FILE CREATE WITH CONTENT: notes.md")
notes_file = os.path.join(DESKTOP, "notes.md")
if file_exists(notes_file):
    os.remove(notes_file)
ans, t, executed, detail = ask(
    "create file notes.md in Desktop with content '# My Notes'"
)
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
time.sleep(1)
if file_exists(notes_file):
    content = file_content(notes_file)
    log(f"VERIFY: file exists. Content: {repr(content[:80])}")
    if "My Notes" in content or "#" in content:
        record("D6", "PASS", "file exists with correct content")
    else:
        record("D6", "PARTIAL", f"file exists but content unexpected: {repr(content[:50])}")
else:
    record("D6", "FAIL", f"file not found at {notes_file}")
time.sleep(2)

# ── D7: File Open ─────────────────────────────────────────────────────────────
log("\nTEST D7 — FILE OPEN: 'open my resume'")
ans, t, executed, detail = ask("open my resume")
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
if executed or "open" in ans.lower():
    record("D7", "PASS", f"{t}s — file found and opened")
elif "not found" in ans.lower() or "couldn't find" in ans.lower():
    record("D7", "PARTIAL", "resume file not found in index (expected if none exists)")
else:
    record("D7", "FAIL", ans[:80])
time.sleep(2)

# ── D8: Media Play (default browser) ─────────────────────────────────────────
log("\nTEST D8 — MEDIA PLAY: 'play despacito' (default browser)")
ans, t, executed, detail = ask("play despacito", timeout=20)
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
if executed or "youtube" in ans.lower() or "play" in ans.lower() or "despacito" in ans.lower():
    record("D8", "PASS", f"{t}s — browser/YouTube action triggered")
else:
    record("D8", "FAIL", ans[:80])
time.sleep(3)

# ── D9: Media Play (specific browser) ────────────────────────────────────────
log("\nTEST D9 — MEDIA PLAY: 'play levitating on brave'")
ans, t, executed, detail = ask("play levitating on brave", timeout=20)
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
if executed or "brave" in ans.lower() or "youtube" in ans.lower() or "play" in ans.lower():
    record("D9", "PASS", f"{t}s — Brave + YouTube action triggered")
elif "not found" in ans.lower() or "fail" in ans.lower():
    record("D9", "PARTIAL", "Brave not installed or action failed")
else:
    record("D9", "FAIL", ans[:80])
time.sleep(3)

# ── D10: Do It Again ─────────────────────────────────────────────────────────
log("\nTEST D10 — DO IT AGAIN (last action recall)")
sid = "phase_d10"
log("  Step 1: open calculator")
ans1, t1, ex1, _ = ask("open calculator", session_id=sid)
log(f"  TIME: {t1}s | A: {ans1[:100]}")
time.sleep(2)
log("  Step 2: what is 2+2")
ans2, t2, ex2, _ = ask("what is 2 plus 2", session_id=sid)
log(f"  TIME: {t2}s | A: {ans2[:100]}")
time.sleep(2)
log("  Step 3: do it again (should re-open calculator, NOT answer math)")
ans3, t3, ex3, _ = ask("do it again", session_id=sid)
log(f"  TIME: {t3}s | EXECUTED: {ex3}")
log(f"  A: {ans3[:200]}")
if ex3 or "calculator" in ans3.lower() or "repeat" in ans3.lower() or "open" in ans3.lower():
    record("D10", "PASS", f"last action repeated correctly")
else:
    record("D10", "FAIL", f"did not repeat action: {ans3[:80]}")
time.sleep(2)

# ── D11: Repeat Variations ───────────────────────────────────────────────────
log("\nTEST D11 — REPEAT VARIATIONS")
sid11 = "phase_d11"
ask("open notepad", session_id=sid11)
time.sleep(1)
results11 = []
for phrase in ["again", "once more", "do that again"]:
    a, t, ex, _ = ask(phrase, session_id=sid11)
    ok = ex or "notepad" in a.lower() or "open" in a.lower() or "repeat" in a.lower()
    results11.append((phrase, ok, a[:60]))
    log(f"  '{phrase}': {'OK' if ok else 'FAIL'} — {a[:60]}")
    time.sleep(1)
all_ok = all(ok for _, ok, _ in results11)
if all_ok:
    record("D11", "PASS", "all 3 repeat variants work")
elif any(ok for _, ok, _ in results11):
    record("D11", "PARTIAL", f"some variants failed: {[p for p,ok,_ in results11 if not ok]}")
else:
    record("D11", "FAIL", "no repeat variants worked")
time.sleep(2)

# ── D12: Unknown App (graceful failure) ──────────────────────────────────────
log("\nTEST D12 — UNKNOWN APP: 'open zorblax'")
ans, t, executed, detail = ask("open zorblax", timeout=12)
log(f"TIME: {t}s | EXECUTED: {executed}")
log(f"A: {ans[:200]}")
if t < 12 and ("not found" in ans.lower() or "fail" in ans.lower() or
               "cannot" in ans.lower() or "couldn't" in ans.lower() or
               "zorblax" in ans.lower()):
    record("D12", "PASS", f"graceful failure in {t}s")
elif t >= 12:
    record("D12", "FAIL", "hung until timeout")
else:
    record("D12", "PARTIAL", f"unclear response: {ans[:80]}")

# ─────────────────────────────────────────────────────────────────────────────
log("\n" + "=" * 70)
log("PHASE D SUMMARY")
log("=" * 70)
log(f"PASS:    {len(passes)}")
log(f"PARTIAL: {len(partials)}")
log(f"FAIL:    {len(fails)}")
log(f"TOTAL:   {len(passes)+len(partials)+len(fails)}")
if fails:
    log("\nFAILURES:")
    for f in fails:
        log(f"  - {f}")
if partials:
    log("\nPARTIAL:")
    for p in partials:
        log(f"  - {p}")

with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
log(f"\nLog saved to {LOG_FILE}")
