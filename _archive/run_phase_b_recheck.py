"""
Phase B — Re-check of previously-failed tests now that Tavily is configured.
Tests: B2 (time routing), B4 (news), B5 (weather), B6 (stocks), B7 (IPL)
"""
import requests, json, time

LOG_FILE = "_test_workspace/results/phase_b_recheck.log"

def ask(question, session_id="b_recheck", provider="auto", timeout=20):
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
                return (d.get("response") or d.get("result") or str(d)).strip(), \
                       round(time.time()-start,1), d.get("provider", provider)
            except Exception:
                pass
        full, prov_used = "", provider
        for line in r.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8", errors="replace")
            if line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                    if "token" in d and d.get("type") != "status":
                        full += d["token"]
                    if d.get("provider"):
                        prov_used = d["provider"]
                    if d.get("_full"):
                        full = d["_full"]
                except Exception:
                    pass
        return full.strip(), round(time.time()-start,1), prov_used
    except Exception as e:
        return f"[ERROR] {e}", round(time.time()-start,1), "error"


tests = [
    ("B2-recheck",  "What time is it for me right now?",             "auto", 10),
    ("B4-recheck",  "What is the latest news in India today?",       "auto", 15),
    ("B5-recheck",  "What is the weather in Hyderabad right now?",   "auto", 12),
    ("B6-recheck",  "What is Apple stock price right now?",          "auto", 15),
    ("B7-recheck",  "Who won the most recent IPL cricket match?",    "auto", 15),
]

lines = []
def log(s):
    print(s, flush=True)
    lines.append(s)

log("=" * 60)
log("PHASE B RE-CHECK (post Tavily key addition)")
log(f"Run date: {time.strftime('%Y-%m-%d %H:%M')}")
log("=" * 60)

for tid, q, prov, timeout in tests:
    log(f"\nTEST: {tid}")
    log(f"Q: {q}")
    ans, t, prov_used = ask(q, provider=prov, timeout=timeout)
    log(f"TIME: {t}s | PROVIDER: {prov_used}")
    log(f"A: {ans[:400].encode('ascii','replace').decode()}")

    fail_phrases = ["couldn't reach", "web sources", "[ERROR]", "unable to"]
    if any(p in ans.lower() for p in fail_phrases) or ans.startswith("[ERROR]"):
        log("RESULT: FAIL")
    elif len(ans) > 10:
        log("RESULT: PASS")
    else:
        log("RESULT: FAIL (empty response)")
    time.sleep(3)

log("\n" + "=" * 60)
with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"Log saved to {LOG_FILE}")
