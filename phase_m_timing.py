"""Phase M — Timing/performance: provider-specific latency p50/p95 over N trials."""
import json, os, time, statistics, subprocess, sys
import urllib.request

BASE = "http://127.0.0.1:5000"
RES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "session_2026_05_16_late")
os.makedirs(RES_DIR, exist_ok=True)

def post_ask(question, provider="auto", session="m"):
    """POST /ask, parse SSE, return (latency_s, response_text)."""
    body = json.dumps({"question": question, "provider": provider, "session_id": session}).encode()
    req = urllib.request.Request(BASE + "/ask", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read().decode()
    except Exception as e:
        return time.time() - t0, f"ERROR: {e}"
    dt = time.time() - t0
    full = None; tokens = []
    for line in data.splitlines():
        line = line.strip()
        if not line.startswith("data:"): continue
        try:
            d = json.loads(line[5:].strip())
        except Exception:
            continue
        if "_full" in d: full = d["_full"]
        elif "token" in d: tokens.append(d["token"])
    text = full if full is not None else "".join(tokens)
    if not text:
        # /ask returns straight JSON when action was taken
        try:
            d = json.loads(data)
            text = d.get("response") or d.get("message") or data[:120]
        except Exception:
            text = data[:120]
    return dt, text

def post_action(query, session="m"):
    body = json.dumps({"query": query, "session_id": session}).encode()
    req = urllib.request.Request(BASE + "/clarify/check", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read().decode()
    except Exception as e:
        return time.time() - t0, f"ERROR: {e}", None
    dt = time.time() - t0
    try:
        d = json.loads(data)
        return dt, (d.get("action_taken") or "?"), (d.get("message") or "")[:120]
    except Exception:
        return dt, "?", data[:120]

def pct(values, p):
    return statistics.quantiles(values, n=100)[p-1] if len(values) >= 5 else max(values)

def trial(name, question, provider, n=5):
    print(f"\n=== {name} ({provider}) — {n} trials ===")
    times = []
    for i in range(n):
        dt, txt = post_ask(question, provider=provider, session=f"{name}_{i}")
        print(f"  t{i+1}: {dt:.2f}s  text: {txt[:80]!r}")
        times.append(dt)
    p50 = statistics.median(times)
    p95 = pct(sorted(times), 95)
    avg = statistics.mean(times)
    print(f"  -> p50={p50:.2f}s  p95={p95:.2f}s  avg={avg:.2f}s  min={min(times):.2f}s  max={max(times):.2f}s")
    return {"name": name, "provider": provider, "n": n, "p50": p50, "p95": p95, "avg": avg, "min": min(times), "max": max(times), "times": times}

def main():
    out = {}
    short = "Reply with the single word: pong"
    out["M1_groq"]      = trial("M1_groq",     short, "groq",     n=5)
    out["M2_gemini"]    = trial("M2_gemini",   short, "gemini",   n=5)

    # M6 — Tavily search
    print("\n=== M6 Tavily search — 5 trials ===")
    times = []
    for i in range(5):
        dt, action, msg = post_action(f"search what is python {i}", session=f"m6_{i}")
        print(f"  t{i+1}: {dt:.2f}s  action={action}  msg={msg[:80]!r}")
        times.append(dt)
    out["M6_search"] = {"p50": statistics.median(times), "max": max(times), "min": min(times), "times": times}

    # M8 — Action latency: take a screenshot (fast)
    print("\n=== M8 Action latency — take screenshot — 5 trials ===")
    times = []
    for i in range(5):
        dt, action, msg = post_action("take a screenshot", session=f"m8_{i}")
        print(f"  t{i+1}: {dt:.2f}s  action={action}")
        times.append(dt)
    out["M8_screenshot"] = {"p50": statistics.median(times), "max": max(times), "min": min(times), "times": times}

    with open(os.path.join(RES_DIR, "phase_m.json"), "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\nWrote", os.path.join(RES_DIR, "phase_m.json"))

if __name__ == "__main__":
    main()
