"""
image_gen.py — Image Generation for Ultron-J BEYOND JARVIS.

Tiers:
1. Together AI / Replicate API (best quality, fast, needs API key)
2. Stable Diffusion local via diffusers (free, slow, needs GPU/CPU)
3. Pollinations.ai (free, no API key, lower quality)

Usage:
    from image_gen import generate_image
    result = generate_image("a futuristic AI lab in Hyderabad at night")
    # result["path"] → saved image path
"""

import base64
import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

_BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR    = os.path.join(_BASE_DIR, "generated_images")
os.makedirs(IMAGE_DIR, exist_ok=True)

try:
    from config import (
        TOGETHER_API_KEY, REPLICATE_API_KEY, OPENAI_API_KEY,
        IMAGE_DEFAULT_SIZE, IMAGE_DEFAULT_STEPS,
    )
except ImportError:
    TOGETHER_API_KEY  = os.environ.get("TOGETHER_API_KEY", "")
    REPLICATE_API_KEY = os.environ.get("REPLICATE_API_KEY", "")
    OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
    IMAGE_DEFAULT_SIZE  = "1024x1024"
    IMAGE_DEFAULT_STEPS = 30

import requests


# =============================================================================
# TIER 1: Together AI (FLUX.1-schnell — fast + high quality)
# =============================================================================

def _generate_together(prompt: str, size: str = "1024x1024",
                        model: str = "black-forest-labs/FLUX.1-schnell") -> Dict:
    if not TOGETHER_API_KEY:
        return {"success": False, "error": "No TOGETHER_API_KEY"}
    w, h = size.split("x")
    try:
        r = requests.post(
            "https://api.together.xyz/v1/images/generations",
            headers={"Authorization": f"Bearer {TOGETHER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": model, "prompt": prompt,
                  "width": int(w), "height": int(h), "steps": 4, "n": 1},
            timeout=60,
        )
        data = r.json()
        if "data" in data and data["data"]:
            url  = data["data"][0].get("url", "")
            b64  = data["data"][0].get("b64_json", "")
            if url:
                return _save_from_url(url, prompt, "together")
            if b64:
                return _save_from_b64(b64, prompt, "together")
        return {"success": False, "error": str(data)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# TIER 2: OpenAI DALL-E 3
# =============================================================================

def _generate_dalle(prompt: str, size: str = "1024x1024") -> Dict:
    if not OPENAI_API_KEY:
        return {"success": False, "error": "No OPENAI_API_KEY"}
    try:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": prompt,
                  "size": size, "n": 1, "response_format": "url"},
            timeout=60,
        )
        data = r.json()
        if "data" in data and data["data"]:
            url = data["data"][0].get("url", "")
            if url:
                return _save_from_url(url, prompt, "dalle3")
        return {"success": False, "error": str(data)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# TIER 3: Pollinations.ai (free, no key)
# =============================================================================

def _generate_pollinations(prompt: str, size: str = "1024x1024",
                             model: str = "flux") -> Dict:
    try:
        encoded = urllib.request.quote(prompt)
        w, h    = size.split("x")
        url     = f"https://image.pollinations.ai/prompt/{encoded}?width={w}&height={h}&model={model}&nologo=true"
        return _save_from_url(url, prompt, "pollinations")
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# SAVE HELPERS
# =============================================================================

def _save_from_url(url: str, prompt: str, source: str) -> Dict:
    try:
        r    = requests.get(url, timeout=60)
        r.raise_for_status()
        path = _save_bytes(r.content, source)
        return {"success": True, "path": path, "url": url, "source": source, "prompt": prompt}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _save_from_b64(b64: str, prompt: str, source: str) -> Dict:
    try:
        data = base64.b64decode(b64)
        path = _save_bytes(data, source)
        return {"success": True, "path": path, "source": source, "prompt": prompt}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _save_bytes(data: bytes, source: str) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(IMAGE_DIR, f"{source}_{ts}.png")
    with open(path, "wb") as f:
        f.write(data)
    return path


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def generate_image(prompt: str, size: str = None,
                   prefer: str = "auto") -> Dict:
    """
    Generate image. Tries providers in order until one succeeds.
    prefer: "together" | "dalle" | "free" | "auto"
    """
    size = size or IMAGE_DEFAULT_SIZE

    tier_map = {
        "together":  [_generate_together, _generate_pollinations],
        "dalle":     [_generate_dalle, _generate_pollinations],
        "free":      [_generate_pollinations],
        "auto":      [_generate_together, _generate_dalle, _generate_pollinations],
    }
    tiers = tier_map.get(prefer, tier_map["auto"])

    for fn in tiers:
        result = fn(prompt, size)
        if result.get("success"):
            return result

    return {"success": False, "error": "All image generation providers failed", "prompt": prompt}


def list_generated_images() -> list:
    return [
        {"file": f, "created": datetime.fromtimestamp(os.path.getctime(
            os.path.join(IMAGE_DIR, f))).isoformat()}
        for f in sorted(os.listdir(IMAGE_DIR))
        if f.endswith((".png", ".jpg", ".webp"))
    ]
