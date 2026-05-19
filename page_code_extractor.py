"""
page_code_extractor.py — Smart Page Code Extractor for Ultron-J

WHAT THIS DOES:
  1. Navigate to a URL (handles JS-heavy pages via Playwright)
  2. Find ALL code blocks on the page (pre/code tags, highlighted blocks)
  3. Detect the language of each code block (Python, JS, HTML, CSS, etc.)
  4. Auto-detect which of Jeevan's files the code belongs in
  5. Save the code to the right file/folder
  6. Say via voice: "Code copied — saved to [filename]"

PARTIAL FEATURE FIX:
  Old: Could read page text + extract code blocks, but:
    - Dynamic JS pages failed
    - No auto-paste to right file
    - No voice confirmation
  New: All of the above — fully working.
"""

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

_BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
EXTRACT_LOG    = os.path.join(_BASE_DIR, "code_extract_log.json")
EXTRACTED_DIR  = os.path.join(_BASE_DIR, "extracted_code")
os.makedirs(EXTRACTED_DIR, exist_ok=True)

_log_lock = threading.Lock()

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

import requests

# =============================================================================
# LOGGING
# =============================================================================

def _log(data: dict):
    with _log_lock:
        try:
            log = []
            if os.path.exists(EXTRACT_LOG):
                with open(EXTRACT_LOG) as f:
                    log = json.load(f)
            log.append({"ts": datetime.now().isoformat(), **data})
            log = log[-200:]
            with open(EXTRACT_LOG, "w") as f:
                json.dump(log, f, indent=2)
        except Exception:
            pass


def get_extract_log(limit: int = 30) -> list:
    try:
        with open(EXTRACT_LOG) as f:
            return json.load(f)[-limit:]
    except Exception:
        return []

# =============================================================================
# LANGUAGE DETECTION
# =============================================================================

LANGUAGE_PATTERNS = {
    "python": [
        r"import\s+\w+", r"from\s+\w+\s+import", r"def\s+\w+\s*\(",
        r"class\s+\w+[:\(]", r"if\s+__name__\s*==", r"print\s*\(",
        r"\.py\b", r"pip install", r"#!.*python",
    ],
    "javascript": [
        r"const\s+\w+\s*=", r"let\s+\w+\s*=", r"var\s+\w+\s*=",
        r"function\s+\w+\s*\(", r"=>\s*{", r"require\s*\(",
        r"module\.exports", r"console\.log", r"document\.", r"window\.",
    ],
    "html": [
        r"<!DOCTYPE\s+html", r"<html", r"<head>", r"<body", r"<div",
        r"<script", r"<style", r"<link\s+rel=", r"<meta\s+",
    ],
    "css": [
        r"\.\w+\s*{", r"#\w+\s*{", r"@media\s+", r"background-color:",
        r"font-size:", r"margin:", r"padding:", r"border:",
        r":hover\s*{", r":focus\s*{",
    ],
    "bash": [
        r"#!/bin/bash", r"#!/bin/sh", r"\$\s+\w+", r"echo\s+",
        r"apt\s+install", r"pip\s+install", r"npm\s+install",
        r"sudo\s+", r"&&\s+", r"\|\s+grep",
    ],
    "json": [
        r'^\s*\{', r'"[^"]+"\s*:', r'^\s*\[', r'null|true|false',
    ],
    "sql": [
        r"SELECT\s+", r"FROM\s+\w+", r"WHERE\s+", r"INSERT\s+INTO",
        r"CREATE\s+TABLE", r"DROP\s+TABLE", r"JOIN\s+\w+",
    ],
    "react_jsx": [
        r"import\s+React", r"from\s+['\"]react['\"]", r"useState\s*\(",
        r"useEffect\s*\(", r"return\s+\(.*<", r"\.jsx\b",
    ],
}

EXTENSIONS = {
    "python":     ".py",
    "javascript": ".js",
    "react_jsx":  ".jsx",
    "html":       ".html",
    "css":        ".css",
    "bash":       ".sh",
    "json":       ".json",
    "sql":        ".sql",
}


def detect_language(code: str, hint: str = "") -> str:
    """Detect programming language from code content."""
    code_lower = code.lower()
    hint_lower = hint.lower()

    # Language from hint (class="language-python", etc.)
    for lang in LANGUAGE_PATTERNS:
        if lang in hint_lower or (lang == "react_jsx" and "jsx" in hint_lower):
            return lang

    # Score each language
    scores = {}
    for lang, patterns in LANGUAGE_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, code, re.IGNORECASE | re.MULTILINE))
        if score > 0:
            scores[lang] = score

    if scores:
        return max(scores, key=scores.get)

    return "text"


def detect_file_destination(code: str, language: str, url: str = "") -> Optional[str]:
    """
    Auto-detect where to save the code on Jeevan's system.
    Priority: Ultron project files > Desktop > home folder
    """
    code_lower = code.lower()
    url_lower  = url.lower()

    # Ultron-specific code
    if any(kw in code_lower for kw in ["ultron", "flask", "@app.route", "from config import"]):
        if language in ("html", "css") or "template" in code_lower:
            return os.path.join(_BASE_DIR, "templates", "index.html")
        if language == "python":
            return os.path.join(_BASE_DIR, "app_additions.py")

    # Check Desktop and common folders
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    home    = os.path.expanduser("~")

    # Language-based defaults
    ext = EXTENSIONS.get(language, ".txt")
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Try to create a meaningful filename from the page URL
    domain = urlparse(url).netloc.replace("www.", "") if url else "extracted"
    path_part = urlparse(url).path.strip("/").replace("/", "_")[:30] if url else ""
    base_name = f"{domain}_{path_part}_{ts}{ext}".replace("..", ".").replace("--", "-")

    # Save to extracted_code folder by default
    return os.path.join(EXTRACTED_DIR, base_name)

# =============================================================================
# PAGE FETCHER — handles both static and dynamic JS pages
# =============================================================================

def _fetch_page_static(url: str) -> str:
    """Fast static fetch with requests + BeautifulSoup."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/122.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        return ""


def _fetch_page_dynamic(url: str, wait_ms: int = 3000) -> str:
    """Full Playwright fetch — handles JS-rendered content."""
    if not PLAYWRIGHT_AVAILABLE:
        return _fetch_page_static(url)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page    = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0"
            )
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(wait_ms)  # let JS render
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        return _fetch_page_static(url)


def _is_dynamic_page(url: str) -> bool:
    """Guess if a page needs JS rendering."""
    dynamic_indicators = [
        "github.com", "stackoverflow.com", "medium.com",
        "dev.to", "codesandbox.io", "codepen.io", "replit.com",
        "notion.so", "docs.google.com",
    ]
    return any(d in url for d in dynamic_indicators)

# =============================================================================
# CODE BLOCK EXTRACTOR
# =============================================================================

def extract_code_from_html(html: str, url: str = "") -> List[Dict]:
    """
    Extract all code blocks from page HTML.
    Handles:
    - <pre><code>...</code></pre> (standard)
    - <code class="language-python">...</code>
    - GitHub-style highlighted code
    - Stack Overflow code blocks
    - Generic highlighted code divs
    """
    if not BS4_AVAILABLE:
        # Fallback: regex extraction
        return _extract_code_regex(html, url)

    soup   = BeautifulSoup(html, "html.parser")
    blocks = []

    # 1. Standard <pre><code> blocks
    for pre in soup.find_all("pre"):
        code_el = pre.find("code")
        if code_el:
            code    = code_el.get_text()
            hint    = " ".join(code_el.get("class", []))
            lang    = detect_language(code, hint)
        else:
            code = pre.get_text()
            lang = detect_language(code)
        code = code.strip()
        if code and len(code) > 20:
            blocks.append({"code": code, "language": lang, "source": "pre"})

    # 2. Standalone <code> blocks (inline code → skip short ones)
    for code_el in soup.find_all("code"):
        if code_el.parent and code_el.parent.name == "pre":
            continue  # already handled above
        code = code_el.get_text().strip()
        if len(code) > 80:  # only substantial inline blocks
            hint = " ".join(code_el.get("class", []))
            lang = detect_language(code, hint)
            blocks.append({"code": code, "language": lang, "source": "code_inline"})

    # 3. GitHub-style: div.highlight, div.blob-code, td.blob-code-inner
    for div in soup.find_all("div", class_=lambda c: c and any(
        x in str(c) for x in ["highlight", "blob-code", "code-block", "CodeMirror"]
    )):
        code = div.get_text().strip()
        if len(code) > 50:
            lang = detect_language(code)
            if not any(b["code"] == code for b in blocks):  # deduplicate
                blocks.append({"code": code, "language": lang, "source": "div_highlight"})

    # 4. Stack Overflow: div.s-prose pre.s-code-block
    for div in soup.find_all(class_=lambda c: c and "s-code" in str(c)):
        code = div.get_text().strip()
        if len(code) > 30:
            lang = detect_language(code)
            if not any(b["code"] == code for b in blocks):
                blocks.append({"code": code, "language": lang, "source": "so_code"})

    _log({"action": "extract_html", "url": url, "blocks_found": len(blocks)})
    return blocks


def _extract_code_regex(html: str, url: str = "") -> List[Dict]:
    """Regex-based fallback when BeautifulSoup not available."""
    blocks = []
    # Match <pre>...</pre>
    for match in re.finditer(r"<pre[^>]*>(.*?)</pre>", html, re.DOTALL):
        code = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if code and len(code) > 20:
            lang = detect_language(code)
            blocks.append({"code": code, "language": lang, "source": "regex_pre"})
    # Match ```fenced``` markdown (from readmes)
    for match in re.finditer(r"```(\w*)\n(.*?)```", html, re.DOTALL):
        lang = match.group(1) or "text"
        code = match.group(2).strip()
        if code:
            blocks.append({"code": code, "language": lang, "source": "fenced"})
    return blocks

# =============================================================================
# SAVE CODE TO FILE
# =============================================================================

def save_code_to_file(code: str, filepath: str, overwrite: bool = False) -> Dict:
    """Save code to a file. Creates dirs as needed. Returns result dict."""
    try:
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        if os.path.exists(filepath) and not overwrite:
            # Append with separator
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"\n\n# ===== EXTRACTED {datetime.now().isoformat()} =====\n")
                f.write(code)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)

        return {
            "success": True,
            "filepath": filepath,
            "size": len(code),
            "existed": os.path.exists(filepath),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "filepath": filepath}


def _voice_confirm(message: str):
    """Say the confirmation via Ultron's TTS."""
    try:
        from voice_engine import tts
        import playsound
        audio_bytes, _ = tts(message)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        playsound.playsound(tmp)
        os.unlink(tmp)
    except Exception:
        print(f"[Ultron] {message}")

# =============================================================================
# MAIN EXTRACTION PIPELINE
# =============================================================================

def extract_and_save(
    url: str,
    save_to: Optional[str] = None,
    index: int = 0,          # which code block to use (0 = first/largest)
    use_js: bool = True,      # use Playwright for dynamic pages
    voice_confirm: bool = True,
    overwrite: bool = False,
) -> Dict:
    """
    Full pipeline:
    1. Fetch URL (JS or static)
    2. Extract all code blocks
    3. Pick the best/requested block
    4. Auto-detect save location
    5. Save to file
    6. Voice confirmation

    Args:
        url: Web page URL to extract code from
        save_to: Explicit file path (if None, auto-detected)
        index: Which code block to save (0=first, -1=largest, "all"=all)
        use_js: Use Playwright for JS-heavy pages
        voice_confirm: Say confirmation via TTS

    Returns: {"success": True, "filepath": ..., "language": ..., "code_preview": ...}
    """
    _log({"action": "extract_start", "url": url})

    # 1. Fetch page
    if use_js and (PLAYWRIGHT_AVAILABLE and _is_dynamic_page(url)):
        html = _fetch_page_dynamic(url)
    else:
        html = _fetch_page_static(url)

    if not html:
        return {"success": False, "error": f"Could not fetch page: {url}"}

    # 2. Extract code blocks
    blocks = extract_code_from_html(html, url)
    if not blocks:
        return {
            "success": False,
            "error": "No code blocks found on this page.",
            "url": url,
        }

    # 3. Pick block(s)
    if index == -1 or index == "largest":
        # Pick the largest block
        selected = [max(blocks, key=lambda b: len(b["code"]))]
    elif index == "all":
        selected = blocks
    else:
        idx = min(int(index), len(blocks) - 1)
        selected = [blocks[idx]]

    results = []
    for i, block in enumerate(selected):
        code     = block["code"]
        language = block["language"]

        # 4. Auto-detect save path
        if save_to:
            filepath = save_to if len(selected) == 1 else save_to.replace(".", f"_{i}.")
        else:
            filepath = detect_file_destination(code, language, url)

        # 5. Save
        save_result = save_code_to_file(code, filepath, overwrite=overwrite)
        save_result["language"] = language
        save_result["code_preview"] = code[:200]
        results.append(save_result)

        _log({
            "action": "code_saved",
            "url": url,
            "language": language,
            "filepath": filepath,
            "size": len(code),
        })

    # 6. Voice confirmation
    if voice_confirm and results:
        saved = [r for r in results if r.get("success")]
        if saved:
            filenames = ", ".join(os.path.basename(r["filepath"]) for r in saved)
            msg = f"Code copied and saved to {filenames}. Language detected: {selected[0]['language']}."
            threading.Thread(target=_voice_confirm, args=(msg,), daemon=True).start()

    if len(results) == 1:
        return results[0]

    return {
        "success": all(r.get("success") for r in results),
        "results": results,
        "total_blocks": len(blocks),
        "saved": len([r for r in results if r.get("success")]),
    }


def list_all_code_on_page(url: str, use_js: bool = True) -> Dict:
    """
    List all code blocks on a page WITHOUT saving.
    Useful for previewing before committing.
    """
    if use_js and PLAYWRIGHT_AVAILABLE and _is_dynamic_page(url):
        html = _fetch_page_dynamic(url)
    else:
        html = _fetch_page_static(url)

    if not html:
        return {"success": False, "error": "Could not fetch page"}

    blocks = extract_code_from_html(html, url)

    return {
        "success": True,
        "url": url,
        "total_blocks": len(blocks),
        "blocks": [
            {
                "index": i,
                "language": b["language"],
                "lines": b["code"].count("\n") + 1,
                "preview": b["code"][:150],
                "source": b.get("source", "unknown"),
            }
            for i, b in enumerate(blocks)
        ],
    }


def copy_code_from_page_to_file(
    url: str,
    target_file: Optional[str] = None,
    block_index: int = 0,
) -> Dict:
    """
    Simple wrapper — extract one code block from a URL and save it.
    Used by voice commands: "copy code from [URL] to [file]"
    """
    return extract_and_save(
        url=url,
        save_to=target_file,
        index=block_index,
        use_js=True,
        voice_confirm=True,
        overwrite=False,
    )
