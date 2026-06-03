"""
Phase C — Cross-Provider Tests
Runs 6 prompts across each provider and records: response, time, provider tag.
Server must be running on http://localhost:5000 before starting this script.
"""
import requests, json, time, sys

PROVIDERS = ["groq", "gemini", "openrouter"]

PROMPTS = [
    ("CP1", "What is the capital of Australia?"),
    ("CP2", "If a train leaves at 3pm going 60mph and a car leaves at 4pm going 75mph, when do they meet 240 miles apart? Just give the time."),
    ("CP3", "Write a 4-line poem about Hyderabad in winter."),
    ("CP4", "Write a Python function that reverses a string. Just the code, no explanation."),
    # CP5 "open notepad" intentionally omitted — covered in Phase D; opening notepad 3x is noise.
    ("CP6", "What is happening in the world today?"),
]

CLOUD_TIMEOUT  = 35
OLLAMA_TIMEOUT = 90

LOG_FILE = "_test_workspace/results/phase_c.log"


def ask(question, provider, timeout):
    start = time.time()
    try:
        r = requests.post(
            "http://localhost:5000/ask",
            json={"question": question, "session_id": f"phase_c_{provider}", "provider": provider},
            stream=True, timeout=timeout,
        )
        content_type = r.headers.get("Content-Type", "")
        if "text/event-stream" not in content_type:
            try:
                d = r.json()
                ans = d.get("response") or d.get("result") or str(d)
                prov_used = d.get("provider", provider)
                return ans.strip()[:600], round(time.time()-start,1), prov_used
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
        return full.strip()[:600], round(time.time()-start,1), prov_used
    except Exception as e:
        return f"[ERROR] {e}", round(time.time()-start,1), "error"


def run():
    lines = []

    def log(s):
        print(s, flush=True)
        lines.append(s)

    log("=" * 72)
    log("PHASE C — CROSS-PROVIDER TESTS")
    log(f"Run date: {time.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 72)

    results = {}   # (prompt_id, provider) -> (ans, t, prov_used)
    fails   = []
    passes  = []

    for pid, prompt in PROMPTS:
        for prov in PROVIDERS:
            timeout = OLLAMA_TIMEOUT if "ollama" in prov else CLOUD_TIMEOUT
            log(f"\n--- {pid} × {prov} ---")
            log(f"Q: {prompt[:80]}")
            ans, t, prov_used = ask(prompt, prov, timeout)
            results[(pid, prov)] = (ans, t, prov_used)

            # Routing check
            routing_ok = (prov_used == prov) or (prov == "openrouter" and prov_used)
            result_ok  = ans and not ans.startswith("[ERROR]") and len(ans) > 5

            if result_ok and t <= (OLLAMA_TIMEOUT if "ollama" in prov else CLOUD_TIMEOUT):
                status = "PASS" if routing_ok else "PARTIAL (wrong provider tag)"
            else:
                status = "FAIL"

            log(f"TIME: {t}s | PROVIDER REQUESTED: {prov} | PROVIDER USED: {prov_used}")
            log(f"A: {ans[:300].encode('ascii','replace').decode()}")
            log(f"RESULT: {status}")

            if status == "PASS":
                passes.append(f"{pid}×{prov}")
            else:
                fails.append(f"{pid}×{prov} — {status} — {ans[:80]}")

            # Brief pause to avoid rate-limit bursts
            if "ollama" not in prov:
                time.sleep(2)

    log("\n" + "=" * 72)
    log("PHASE C SUMMARY")
    log("=" * 72)
    log(f"PASS:  {len(passes)}")
    log(f"FAIL:  {len(fails)}")
    log(f"TOTAL: {len(PROVIDERS) * len(PROMPTS)}")

    if fails:
        log("\nFAILURES:")
        for f in fails:
            log(f"  - {f}")

    log("\nPROVIDER × PROMPT MATRIX (time in seconds):")
    header = f"{'':20}" + "".join(f"{pid:>12}" for pid, _ in PROMPTS)
    log(header)
    for prov in PROVIDERS:
        row = f"{prov[:20]:20}"
        for pid, _ in PROMPTS:
            ans, t, _ = results.get((pid, prov), ("?", "?", "?"))
            ok = "ok" if (ans and not ans.startswith("[ERROR]")) else "FAIL"
            row += f"{str(t)+'s('+ok+')':>12}"
        log(row)

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nLog saved to {LOG_FILE}")


if __name__ == "__main__":
    print("Checking server...", flush=True)
    try:
        r = requests.get("http://localhost:5000/status", timeout=5)
        d = r.json()
        print(f"Server OK — {d.get('agent','?')} v{d.get('version','?')}", flush=True)
    except Exception as e:
        print(f"[ERROR] Server not responding: {e}")
        print("Start the server first: python app.py")
        sys.exit(1)
    run()
