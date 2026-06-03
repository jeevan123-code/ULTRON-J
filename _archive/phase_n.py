"""Phase N — Integration: N1 (search + save), N4 (multi-provider parity)."""
import json, os, time, urllib.request
BASE = "http://127.0.0.1:5000"
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "session_2026_05_16_late")
os.makedirs(RES, exist_ok=True)

def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode()

def parse_ask(data):
    full = None; tokens = []
    for line in data.splitlines():
        line = line.strip()
        if not line.startswith("data:"): continue
        try: d = json.loads(line[5:].strip())
        except: continue
        if "_full" in d: full = d["_full"]
        elif "token" in d: tokens.append(d["token"])
    text = full if full is not None else "".join(tokens)
    if not text:
        try: text = json.loads(data).get("response","")[:300]
        except: text = data[:200]
    return text

# === N1 — search + save to file ===
print("=== N1: search lofi music news, save summary to Desktop\\solar_news.txt ===")
target = r"C:\Users\xjoke\OneDrive\Desktop\solar_news.txt"
if os.path.exists(target): os.remove(target)
# Step 1 — search and capture summary
t0 = time.time()
d1 = post("/clarify/check", {"query": "search latest news on solar power", "session_id": "n1"})
print(f"  search took {time.time()-t0:.2f}s")
j1 = json.loads(d1)
summary = j1.get("message") or ""
print(f"  action: {j1.get('action_taken')}, summary chars: {len(summary)}, preview: {summary[:120]!r}")

# Step 2 — save the summary to a file using create_file action
content_escaped = summary.replace("\n", " ").replace("\"", "'")[:800]
t1 = time.time()
d2 = post("/clarify/check", {"query": f"create file solar_news.txt on desktop with content {content_escaped}", "session_id": "n1"})
print(f"  save took {time.time()-t1:.2f}s")
j2 = json.loads(d2)
print(f"  action: {j2.get('action_taken')}, success: {j2.get('success')}")
print(f"  message: {(j2.get('message') or '')[:200]!r}")

# Step 3 — verify on disk
exists = os.path.exists(target)
print(f"  file exists on disk: {exists}")
if exists:
    with open(target, encoding="utf-8", errors="replace") as f:
        body = f.read()
    print(f"  file size: {os.path.getsize(target)} bytes")
    print(f"  file content preview: {body[:200]!r}")
    print(f"  contains 'solar' (case-insens): {'solar' in body.lower()}")
print()

# === N4 — multi-provider parity ===
print("=== N4: explain quantum computing in 1 sentence — groq, gemini ===")
q = "Explain quantum computing in 1 sentence."
results = {}
for prov in ("groq", "gemini"):
    t0 = time.time()
    d = post("/ask", {"question": q, "provider": prov, "session_id": "n4"})
    text = parse_ask(d)
    dt = time.time() - t0
    results[prov] = {"time": dt, "len": len(text), "preview": text[:300]}
    print(f"  {prov:8s}: {dt:5.2f}s  ({len(text)} chars)  {text[:140]!r}")
    # Verify provider tag
    if "via" in text.lower() or prov in text.lower():
        results[prov]["tag_visible"] = True
print()

# Save
with open(os.path.join(RES, "phase_n.json"), "w") as f:
    json.dump({"N1_file_exists": exists, "N1_summary_chars": len(summary), "N4": results}, f, indent=2, default=str)
print("Wrote phase_n.json")
