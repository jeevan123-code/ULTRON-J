"""
German tutor -- backend.

This server has three jobs and nothing else:

  1. Serve index.html to the browser.
  2. Mint a short-lived "ephemeral token" so the browser can talk to OpenAI
     directly without ever seeing your real API key.
  3. Append your mistakes to mistakes.json.

Run it with:  python main.py
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import prompts

# Load OPENAI_API_KEY from the .env file sitting next to this script.
HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

# ---------------------------------------------------------------------------
# OpenAI settings.
#
# These are the current Realtime API values (checked against the docs, not
# from memory). If OpenAI renames something, this is the only place you need
# to edit -- the browser asks the server for these values at connect time.
# ---------------------------------------------------------------------------

# Speech-to-speech model. "gpt-realtime" is the stable alias that always
# points at the current version. Swap to "gpt-realtime-mini" to cut the cost
# by roughly two thirds (see the cost section of README.md).
MODEL = "gpt-realtime"

# Where the server asks for a short-lived browser token.
CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"

# Where the browser sends its WebRTC offer. The browser gets this URL from
# the server, so you only ever change it here.
REALTIME_CALLS_URL = "https://api.openai.com/v1/realtime/calls"

# The voice the tutor speaks with. Others include: alloy, ash, ballad, cedar,
# coral, echo, sage, shimmer, verse.
VOICE = "marin"

# Model used to transcribe what YOU said. This is what gets written into
# mistakes.json, and it also helps the tutor hear you accurately.
TRANSCRIBE_MODEL = "gpt-4o-transcribe"

# How long the browser token stays valid. It only needs to survive long
# enough to open the connection; the call itself continues afterwards.
TOKEN_LIFETIME_SECONDS = 600

MISTAKES_FILE = HERE / "mistakes.json"

app = FastAPI(title="German tutor")


# ---------------------------------------------------------------------------
# Serving the page
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    """Hand the browser the one and only page."""
    return FileResponse(HERE / "index.html")


@app.get("/api/config")
def config():
    """Levels and scenarios, so the buttons and dropdown build themselves.

    This is why adding a scenario to prompts.py makes it appear in the
    dropdown without editing any HTML.
    """
    return {
        "levels": list(prompts.LEVELS.keys()),
        "default_level": prompts.DEFAULT_LEVEL,
        "scenarios": [
            {"id": key, "label": value["label"]}
            for key, value in prompts.SCENARIOS.items()
        ],
        "default_scenario": prompts.DEFAULT_SCENARIO,
    }


# ---------------------------------------------------------------------------
# Minting the browser's short-lived token
# ---------------------------------------------------------------------------
def _session_config(level: str, scenario: str) -> dict:
    """Build the session settings we want OpenAI to use for this call."""
    return {
        "type": "realtime",
        "model": MODEL,
        "instructions": prompts.build_instructions(level, scenario),
        # We only want to hear the tutor, never read it. No text on screen.
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                # Transcribe what I say, so corrections can be logged.
                "transcription": {"model": TRANSCRIBE_MODEL, "language": "de"},
                # Turn detection stays ON even though we push to talk. This is
                # what lets the tutor cut in while you are still holding the
                # button -- "interrupt me immediately" in the instructions
                # only works if the model is allowed to start talking on its
                # own. "eagerness: high" makes it jump in sooner.
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": "high",
                    "create_response": True,
                    "interrupt_response": True,
                },
            },
            "output": {"voice": VOICE},
        },
        # The tutor calls this to log a correction. Defined in prompts.py.
        "tools": [prompts.LOG_MISTAKE_TOOL],
        "tool_choice": "auto",
    }


class SessionRequest(BaseModel):
    level: str = prompts.DEFAULT_LEVEL
    scenario: str = prompts.DEFAULT_SCENARIO


@app.post("/api/session")
async def create_session(req: SessionRequest):
    """Ask OpenAI for a token the browser is allowed to use.

    The token is tied to this session's settings and expires in minutes, so
    it is safe to hand to the browser. Your real key stays here.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="No OPENAI_API_KEY found. Put it in german-tutor/.env "
                   "(see README.md).",
        )

    payload = {
        "expires_after": {"anchor": "created_at",
                          "seconds": TOKEN_LIFETIME_SECONDS},
        "session": _session_config(req.level, req.scenario),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            CLIENT_SECRETS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code >= 400:
        # Pass OpenAI's own error text through -- it is usually specific
        # ("model not found", "insufficient quota") and saves you guessing.
        raise HTTPException(status_code=response.status_code,
                            detail=f"OpenAI rejected the request: {response.text}")

    data = response.json()

    # The token string lives in "value". Older/other shapes nest it under
    # "client_secret", so accept either rather than crashing.
    secret = data.get("value")
    if secret is None:
        nested = data.get("client_secret")
        secret = nested.get("value") if isinstance(nested, dict) else nested
    if not secret:
        raise HTTPException(
            status_code=500,
            detail=f"Could not find the token in OpenAI's reply: {data}")

    return {
        "client_secret": secret,
        "webrtc_url": REALTIME_CALLS_URL,
        "model": MODEL,
    }


@app.get("/api/instructions")
def instructions(level: str = prompts.DEFAULT_LEVEL,
                 scenario: str = prompts.DEFAULT_SCENARIO):
    """The instruction text on its own.

    Used when you change level or scenario in the middle of a conversation:
    the browser fetches the new text and sends it down the open connection,
    so the call is never interrupted.
    """
    return {"instructions": prompts.build_instructions(level, scenario)}


# ---------------------------------------------------------------------------
# The mistake log
# ---------------------------------------------------------------------------
class Mistake(BaseModel):
    said: str
    correction: str
    tag: str
    note: Optional[str] = None
    level: Optional[str] = None
    scenario: Optional[str] = None


@app.post("/api/mistakes")
def log_mistake(mistake: Mistake):
    """Append one correction to mistakes.json.

    Append-only on purpose: nothing is ever edited or deleted, so the file is
    a plain running record you can read or analyse later.
    """
    entry = mistake.model_dump()
    entry["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Read what is there, add one line, write it back. Fine for one person.
    existing = []
    if MISTAKES_FILE.exists():
        try:
            existing = json.loads(MISTAKES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Never lose a session because the file got mangled.
            existing = []
    if not isinstance(existing, list):
        existing = []

    existing.append(entry)
    MISTAKES_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"  logged [{entry['tag']}]  {entry['said']!r} -> {entry['correction']!r}")
    return {"ok": True, "total": len(existing)}


if __name__ == "__main__":
    print("\n  German tutor running at  http://localhost:8000\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
