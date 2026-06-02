"""
Open-Any-App Verification
Picks 6 apps from Ultron's system_index that were NOT tested in Phase D.
For each: snapshots running processes, asks Ultron to open it, snapshots again.
PASS only when a NEW matching process appears.
"""
import requests, json, time, sys, subprocess, os

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

URL = "http://localhost:5000/ask"

# (display name, query for Ultron, substring of process name to match)
TARGETS = [
    ("Paint",         "open paint",          "mspaint"),
    ("WordPad",       "open wordpad",        "wordpad"),
    ("Snipping Tool", "open snipping tool",  "SnippingTool"),
    ("Cursor",        "open cursor",         "cursor"),
    ("CapCut",        "open capcut",         "capcut"),
    ("File Explorer", "open file explorer",  "explorer"),
]


def ps_pids(name_substr):
    """Return set of PIDs whose process name contains substring (case-insensitive)."""
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Process | Where-Object {{$_.ProcessName -like '*{name_substr}*'}} | ForEach-Object {{$_.Id}}"],
            text=True, errors="replace", timeout=10,
        )
        return set(int(line.strip()) for line in raw.splitlines() if line.strip().isdigit())
    except Exception:
        return set()


def ask(question, timeout=15):
    start = time.time()
    try:
        r = requests.post(
            URL,
            json={"question": question, "session_id": "open_any_app", "provider": "auto"},
            stream=True, timeout=timeout,
        )
        full = ""
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
                except Exception:
                    pass
        return full.strip()[:200], round(time.time() - start, 1)
    except Exception as e:
        return f"[ERROR] {e}", round(time.time() - start, 1)


def main():
    print("=" * 72)
    print("OPEN-ANY-APP VERIFICATION")
    print(f"Server: {requests.get('http://localhost:5000/status', timeout=5).json().get('agent')}")
    print("=" * 72)

    results = []
    for label, query, pname in TARGETS:
        before = ps_pids(pname)
        print(f"\n>>> {label}  (query='{query}', match='{pname}')")
        print(f"    PIDs before: {sorted(before) or '(none)'}")
        reply, t = ask(query)
        print(f"    Reply: {reply}")
        time.sleep(4)
        after = ps_pids(pname)
        new = after - before
        print(f"    PIDs after:  {sorted(after) or '(none)'}")
        verdict = "PASS" if new else "FAIL"
        if not new and reply and ("not found" in reply.lower() or "failed" in reply.lower()):
            verdict = "FAIL-not-in-index"
        print(f"    NEW PIDs: {sorted(new) or '(none)'}  →  {verdict}")
        results.append((label, verdict, sorted(new), reply[:80], t))

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    passes = sum(1 for _, v, *_ in results if v == "PASS")
    print(f"PASS: {passes} / {len(results)}")
    for label, verdict, new, reply, t in results:
        print(f"  {label:18}  {verdict:18}  pids={new}  ({t}s)  {reply}")


if __name__ == "__main__":
    main()
