"""
ultron_test.py — Comprehensive test suite for Ultron-J
Tests: intent router, Groq, Gemini, OpenRouter, Ollama, memory, code search
Run: python ultron_test.py   (app.py must be running)
"""

import sys
import requests
import json
import time

# Force UTF-8 output so Unicode in LLM responses doesn't crash on Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:5000"
PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"

results = []


def ask(question, provider="auto", session_id="test"):
    """Send question to /ask, collect full streamed response. Returns (text, provider_used)."""
    try:
        resp = requests.post(
            f"{BASE}/ask",
            json={"question": question, "provider": provider, "session_id": session_id},
            stream=True,
            timeout=40,
        )
        if resp.status_code != 200:
            return f"[HTTP {resp.status_code}] {resp.text[:300]}", "error"

        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            full = ""
            used_provider = provider
            for raw in resp.iter_lines():
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                if raw.startswith("data: "):
                    try:
                        chunk = json.loads(raw[6:])
                        if chunk.get("done"):
                            full = chunk.get("_full", full)
                            used_provider = chunk.get("provider", provider)
                            break
                        elif "token" in chunk:
                            full += chunk["token"]
                    except Exception:
                        pass
            return full.strip(), used_provider
        else:
            data = resp.json()
            text = (
                data.get("response") or
                data.get("message") or
                data.get("result") or
                str(data)
            )
            return str(text).strip(), data.get("provider", provider)
    except Exception as e:
        return f"[ERROR] {e}", "error"


def test(label, question, provider="auto", expect=None, skip_if_offline=False):
    """Run one test, print result, append to results list."""
    print(f"\n  Q : {question}")
    print(f"  PR: {provider}")

    answer, used = ask(question, provider)
    short = answer[:280].replace("\n", " | ")

    status = None
    if "ERROR" in answer and skip_if_offline:
        status = SKIP
    elif expect:
        status = PASS if expect.lower() in answer.lower() else FAIL
    else:
        status = PASS if answer and "ERROR" not in answer else FAIL

    tag = f"{status} [{label}]"
    print(f"  A : {short}")
    print(f"  => {tag}  (provider used: {used})")
    results.append((label, status, used))
    return answer


def section(title):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


if __name__ == "__main__":
    # ─────────────────────────────────────────────────────────────────────────────
    # 1. INTENT ROUTER  (pre-LLM — must execute in <200ms, no cloud call)
    # ─────────────────────────────────────────────────────────────────────────────
    section("1 / INTENT ROUTER  —  direct execution, no LLM")

    test("time",            "what time is it",        expect=":")
    test("screenshot",      "take screenshot")
    test("volume_up",       "volume up")
    test("volume_down",     "volume down")
    test("mute",            "mute")
    test("media_pause",     "pause")
    test("media_next",      "next song")
    test("scroll_down",     "scroll down")
    test("scroll_up",       "scroll up")
    test("minimize",        "minimize window")
    test("press_escape",    "press escape")
    test("type_text",       "type: hello ultron")
    test("open_app",        "open notepad")
    test("close_window",    "close window")
    test("repeat",          "do that again")


    # ─────────────────────────────────────────────────────────────────────────────
    # 2. SAME QUESTION — ALL THREE CLOUD PROVIDERS
    # ─────────────────────────────────────────────────────────────────────────────
    section("2 / SAME QUESTION  —  Groq vs Gemini vs OpenRouter")

    SAME_Q = "What is 15 multiplied by 7? Reply with ONLY the number, nothing else."
    for prov in ["groq", "gemini", "openrouter"]:
        test(f"math_{prov}", SAME_Q, provider=prov, expect="105")


    # ─────────────────────────────────────────────────────────────────────────────
    # 3. DIFFERENT TASKS — ONE PER PROVIDER
    # ─────────────────────────────────────────────────────────────────────────────
    section("3 / DIFFERENT TASKS  —  one per provider")

    test("logic_groq",
         "It always rains when there are dark clouds. There are dark clouds now. "
         "Will it rain? Answer Yes or No and explain in one sentence.",
         provider="groq", expect="yes")

    test("code_gemini",
         "Write a Python one-liner that reverses a string variable named s. "
         "Just the expression, no explanation.",
         provider="gemini", expect="[::-1]")

    test("reason_openrouter",
         "I have 10 oranges. I eat 3, give away 2, and buy 5 more. "
         "How many oranges do I have? Show your working.",
         provider="openrouter", expect="10")


    # ─────────────────────────────────────────────────────────────────────────────
    # 4. OLLAMA — local offline model
    # ─────────────────────────────────────────────────────────────────────────────
    section("4 / OLLAMA  —  local offline model (skip if not running)")

    test("ollama_basic",
         "What is the capital of France? One word only.",
         provider="ollama:mistral",
         expect="paris",
         skip_if_offline=True)

    test("ollama_code",
         "Write a Python function that adds two numbers. No explanation.",
         provider="ollama:mistral",
         skip_if_offline=True)

    test("ollama_tinyllama",
         "Say hello in one sentence.",
         provider="ollama:tinyllama",
         skip_if_offline=True)


    # ─────────────────────────────────────────────────────────────────────────────
    # 5. MEMORY — store then recall
    # ─────────────────────────────────────────────────────────────────────────────
    section("5 / MEMORY  —  remember and recall")

    test("mem_store",  "remember that my favourite programming language is Python")
    time.sleep(1)
    test("mem_recall", "what is my favourite programming language?", expect="python")
    test("mem_store2", "remember that Jeevan lives in Hyderabad")
    time.sleep(1)
    test("mem_recall2","where do I live?", expect="hyderabad")


    # ─────────────────────────────────────────────────────────────────────────────
    # 6. CODE SEARCH — tests code_index + vector_store integration
    # ─────────────────────────────────────────────────────────────────────────────
    section("6 / CODE SEARCH  —  semantic code index")

    test("code_find_fn",     "where is detect_intent defined?",        expect="intent_router")
    test("code_find_route",  "which function handles the /ask route?",  expect="ask")
    test("code_find_stream", "which function streams the LLM response?", expect="stream_llm")
    test("code_find_memory", "where is vector_store recall function?",  expect="vector_store")


    # ─────────────────────────────────────────────────────────────────────────────
    # 7. MULTI-STEP REASONING — makes the LLM think harder
    # ─────────────────────────────────────────────────────────────────────────────
    section("7 / MULTI-STEP REASONING  —  auto provider")

    test("steps_math",
         "A train travels at 80 km/h. It leaves at 9:00 AM. "
         "How far has it travelled by 11:30 AM?",
         expect="200")

    test("steps_logic",
         "All programmers drink coffee. Jeevan is a programmer. "
         "Does Jeevan drink coffee? Yes or No.",
         expect="yes")

    test("steps_code_explain",
         "In Python, what does [::-1] do to a list? One sentence.",
         expect="revers")


    # ─────────────────────────────────────────────────────────────────────────────
    # 8. PERSONALITY & CAPABILITY AWARENESS
    # ─────────────────────────────────────────────────────────────────────────────
    section("8 / PERSONALITY + CAPABILITY AWARENESS")

    test("who_are_you",    "who are you?",         expect="ultron")
    test("capabilities",   "what can you do?",     expect="app")
    test("cant_do_check",  "can you take a screenshot?")  # intent router executes it — pass if any response


    # ─────────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────────────
    section("FINAL SUMMARY")

    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    skipped = sum(1 for _, s, _ in results if s == SKIP)
    total = len(results)

    print(f"\n  Total : {total}  |  Passed: {passed}  |  Failed: {failed}  |  Skipped: {skipped}\n")

    if failed:
        print("  FAILED tests:")
        for label, status, used in results:
            if status == FAIL:
                print(f"    - {label}  (provider: {used})")

    if skipped:
        print("\n  SKIPPED tests (Ollama offline or not installed):")
        for label, status, used in results:
            if status == SKIP:
                print(f"    - {label}")

    print(f"\n{'='*65}\n")
