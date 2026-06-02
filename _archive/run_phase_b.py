import requests, json, time, sys

def ask(question, session_id="phase_b_test", provider="groq", timeout=65):
    start = time.time()
    try:
        r = requests.post(
            "http://localhost:5000/ask",
            json={"question": question, "session_id": session_id, "provider": provider},
            stream=True, timeout=timeout
        )
        # Handle plain JSON response (non-streaming intents like weather, greeting)
        content_type = r.headers.get("Content-Type", "")
        if "text/event-stream" not in content_type:
            try:
                d = r.json()
                ans = d.get("response") or d.get("result") or str(d)
                elapsed = round(time.time() - start, 1)
                return ans.strip(), elapsed, "json-route"
            except Exception:
                pass

        full = ""
        provider_used = "?"
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
                        provider_used = d["provider"]
                    if d.get("_full"):
                        full = d["_full"]
                except Exception:
                    pass
        elapsed = round(time.time() - start, 1)
        return full.strip(), elapsed, provider_used
    except Exception as e:
        return f"[ERROR] {e}", round(time.time() - start, 1), "error"


tests = [
    ("B1", "What is today's date?"),
    ("B2", "What time is it for me right now?"),
    ("B3", "Where am I located?"),
    ("B4", "What is the latest news in India today?"),
    ("B5", "What is the weather in Hyderabad right now?"),
    ("B6", "What is Apple stock price right now?"),
    ("B7", "Who won the most recent IPL cricket match?"),
    ("B9", "Explain photosynthesis in 2 sentences."),
]

results = []
for tid, q in tests:
    print(f"\n{'='*60}", flush=True)
    print(f"TEST: {tid}", flush=True)
    print(f"Q: {q}", flush=True)
    ans, t, prov = ask(q)
    print(f"TIME: {t}s | PROVIDER: {prov}", flush=True)
    print("A: " + ans[:500].encode("ascii", errors="replace").decode(), flush=True)
    results.append((tid, q, ans, t, prov))
    time.sleep(3)  # avoid rate-limit burst

# B10 multi-turn
print(f"\n{'='*60}", flush=True)
print("TEST: B10 (multi-turn)", flush=True)
sid = "phase_b10_test"
for turn, q in [
    ("B10-1", "I am planning a trip to Goa next week."),
    ("B10-2", "What is the best beach there?"),
    ("B10-3", "Book a hotel near it."),
]:
    print(f"\n  TURN {turn}: {q}", flush=True)
    ans, t, prov = ask(q, session_id=sid)
    print(f"  TIME: {t}s | PROVIDER: {prov}", flush=True)
    print("  A: " + ans[:300].encode("ascii", errors="replace").decode(), flush=True)
    time.sleep(4)

print("\n\nDONE.", flush=True)
