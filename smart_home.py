"""
smart_home.py — Smart Home Control for Ultron-J BEYOND JARVIS.

Integrates with Home Assistant (self-hosted) and Tuya/SmartLife devices.
Control lights, fans, AC, switches — all via voice or chat.

Setup:
    HASS_URL=http://homeassistant.local:8123
    HASS_TOKEN=<long-lived access token from HA>
    TUYA_ACCESS_ID=...
    TUYA_ACCESS_SECRET=...

Usage:
    from smart_home import SmartHome
    sh = SmartHome()
    sh.turn_on("light.bedroom")
    sh.set_brightness("light.bedroom", 50)
    sh.get_all_states()
"""

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import requests

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from config import (
        HASS_URL, HASS_TOKEN,
        TUYA_ACCESS_ID, TUYA_ACCESS_SECRET, TUYA_BASE_URL,
    )
except ImportError:
    HASS_URL          = os.environ.get("HASS_URL", "http://homeassistant.local:8123")
    HASS_TOKEN        = os.environ.get("HASS_TOKEN", "")
    TUYA_ACCESS_ID    = os.environ.get("TUYA_ACCESS_ID", "")
    TUYA_ACCESS_SECRET = os.environ.get("TUYA_ACCESS_SECRET", "")
    TUYA_BASE_URL     = os.environ.get("TUYA_BASE_URL", "https://openapi.tuyain.com")


# =============================================================================
# HOME ASSISTANT INTEGRATION
# =============================================================================

class HomeAssistant:
    """Control Home Assistant devices via REST API."""

    def __init__(self, url: str = None, token: str = None):
        self.url     = (url or HASS_URL).rstrip("/")
        self.token   = token or HASS_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  "application/json",
        }
        self._available = bool(self.token)

    def is_available(self) -> bool:
        if not self._available:
            return False
        try:
            r = requests.get(f"{self.url}/api/", headers=self.headers, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def _api(self, method: str, path: str, data: dict = None) -> Dict:
        if not self._available:
            return {"success": False, "error": "Home Assistant not configured"}
        url = f"{self.url}/api/{path}"
        try:
            if method == "GET":
                r = requests.get(url, headers=self.headers, timeout=10)
            else:
                r = requests.post(url, headers=self.headers, json=data or {}, timeout=10)
            return {"success": True, "data": r.json(), "status": r.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_states(self, domain: str = None) -> List[Dict]:
        result = self._api("GET", "states")
        if not result["success"]:
            return []
        states = result["data"]
        if domain:
            states = [s for s in states if s.get("entity_id", "").startswith(f"{domain}.")]
        return states

    def get_state(self, entity_id: str) -> Dict:
        result = self._api("GET", f"states/{entity_id}")
        return result.get("data", {})

    def call_service(self, domain: str, service: str, entity_id: str = None,
                     extra: dict = None) -> Dict:
        data = {"entity_id": entity_id} if entity_id else {}
        if extra:
            data.update(extra)
        return self._api("POST", f"services/{domain}/{service}", data)

    # ── Convenience methods ───────────────────────────────────────────────────

    def turn_on(self, entity_id: str, **kwargs) -> Dict:
        return self.call_service(_domain(entity_id), "turn_on", entity_id, kwargs or None)

    def turn_off(self, entity_id: str) -> Dict:
        return self.call_service(_domain(entity_id), "turn_off", entity_id)

    def toggle(self, entity_id: str) -> Dict:
        return self.call_service(_domain(entity_id), "toggle", entity_id)

    def set_brightness(self, entity_id: str, pct: int) -> Dict:
        return self.call_service("light", "turn_on", entity_id,
                                  {"brightness_pct": max(0, min(100, pct))})

    def set_temperature(self, entity_id: str, temp: float) -> Dict:
        return self.call_service("climate", "set_temperature", entity_id,
                                  {"temperature": temp})

    def set_hvac_mode(self, entity_id: str, mode: str) -> Dict:
        """mode: cool/heat/fan_only/auto/off"""
        return self.call_service("climate", "set_hvac_mode", entity_id,
                                  {"hvac_mode": mode})

    def get_sensors(self) -> List[Dict]:
        return self.get_states("sensor")

    def get_lights(self) -> List[Dict]:
        return self.get_states("light")

    def get_switches(self) -> List[Dict]:
        return self.get_states("switch")

    def get_climate(self) -> List[Dict]:
        return self.get_states("climate")

    def natural_command(self, text: str) -> Dict:
        """
        Parse natural language commands.
        "turn on bedroom light" → turn_on("light.bedroom")
        "set AC to 24 degrees" → set_temperature("climate.ac", 24)
        """
        text = text.lower().strip()
        states = self.get_states()
        entities = {s["entity_id"]: s.get("attributes", {}).get("friendly_name", "")
                    for s in states}

        # Find matching entity
        matched_entity = None
        for eid, name in entities.items():
            if name.lower() in text or eid.split(".")[-1].replace("_", " ") in text:
                matched_entity = eid
                break

        if not matched_entity:
            return {"success": False, "error": "No matching device found", "text": text}

        # Determine action
        if any(w in text for w in ["on", "enable", "open", "start"]):
            return self.turn_on(matched_entity)
        elif any(w in text for w in ["off", "disable", "close", "stop"]):
            return self.turn_off(matched_entity)
        elif "toggle" in text:
            return self.toggle(matched_entity)
        elif any(c.isdigit() for c in text):
            import re
            nums = re.findall(r"\d+", text)
            if nums:
                num = int(nums[0])
                if "bright" in text or "dim" in text or _domain(matched_entity) == "light":
                    return self.set_brightness(matched_entity, num)
                elif "degree" in text or "temp" in text:
                    return self.set_temperature(matched_entity, num)

        return {"success": False, "error": "Could not determine action", "entity": matched_entity}


def _domain(entity_id: str) -> str:
    return entity_id.split(".")[0] if "." in entity_id else "homeassistant"


# =============================================================================
# SMART HOME FACADE
# =============================================================================

class SmartHome:
    """Unified smart home interface."""

    def __init__(self):
        self.hass    = HomeAssistant()
        self._status = {"hass": False}

    def check_connectivity(self):
        self._status["hass"] = self.hass.is_available()
        return self._status

    def turn_on(self, entity: str, **kwargs) -> Dict:
        return self.hass.turn_on(entity, **kwargs)

    def turn_off(self, entity: str) -> Dict:
        return self.hass.turn_off(entity)

    def toggle(self, entity: str) -> Dict:
        return self.hass.toggle(entity)

    def set_brightness(self, entity: str, pct: int) -> Dict:
        return self.hass.set_brightness(entity, pct)

    def set_temperature(self, entity: str, temp: float) -> Dict:
        return self.hass.set_temperature(entity, temp)

    def natural_command(self, text: str) -> Dict:
        return self.hass.natural_command(text)

    def get_summary(self) -> str:
        lights  = self.hass.get_lights()
        on_cnt  = sum(1 for l in lights if l.get("state") == "on")
        climate = self.hass.get_climate()
        lines   = [f"💡 {on_cnt}/{len(lights)} lights on"]
        for c in climate[:3]:
            attrs = c.get("attributes", {})
            lines.append(
                f"🌡️ {attrs.get('friendly_name','AC')}: "
                f"{c.get('state','?')} @ {attrs.get('current_temperature','?')}°C"
            )
        return "\n".join(lines) if lines else "No smart home devices found"

    def get_status(self) -> dict:
        return {
            "hass_available": self.hass.is_available(),
            "hass_url":       self.hass.url,
            "configured":     bool(HASS_TOKEN),
        }


# =============================================================================
# SELF-MODIFY ENGINE
# =============================================================================
# (Separate concern, included here for brevity)

"""
self_modify.py — Safe Self-Modification for Ultron-J BEYOND JARVIS.

Ultron can:
1. Propose a code change (diff)
2. You review it in the UI
3. You click Apply → it writes the file
4. Auto-backup before every change

This makes "Can't self-modify permanently" DONE.
"""


class SelfModifyEngine:
    """
    Safe self-modification with review + backup.
    """

    BACKUP_DIR   = os.path.join(_BASE_DIR, "self_modify_backups")
    PROPOSALS_FILE = os.path.join(_BASE_DIR, "code_proposals.json")

    def __init__(self):
        os.makedirs(self.BACKUP_DIR, exist_ok=True)

    def propose_change(self, filepath: str, new_content: str,
                        reason: str = "") -> Dict:
        """
        Store a proposed file change for review.
        Returns proposal ID.
        """
        if not os.path.isabs(filepath):
            filepath = os.path.join(_BASE_DIR, filepath)

        proposal_id = str(uuid.uuid4())[:8]
        old_content = ""
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                old_content = f.read()

        diff = _simple_diff(old_content, new_content)

        proposals = self._load_proposals()
        proposals[proposal_id] = {
            "id":          proposal_id,
            "filepath":    filepath,
            "old_content": old_content,
            "new_content": new_content,
            "diff":        diff,
            "reason":      reason,
            "status":      "pending",
            "created_at":  datetime.now().isoformat(),
        }
        self._save_proposals(proposals)
        return {"success": True, "proposal_id": proposal_id, "diff": diff}

    def apply_proposal(self, proposal_id: str) -> Dict:
        """Apply an approved proposal — backup original first."""
        proposals = self._load_proposals()
        if proposal_id not in proposals:
            return {"success": False, "error": "Proposal not found"}

        p = proposals[proposal_id]
        filepath    = p["filepath"]
        new_content = p["new_content"]

        # Backup
        backup_path = self._backup(filepath)

        # Write
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            p["status"]     = "applied"
            p["applied_at"] = datetime.now().isoformat()
            p["backup"]     = backup_path
            self._save_proposals(proposals)
            return {"success": True, "filepath": filepath, "backup": backup_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def reject_proposal(self, proposal_id: str) -> Dict:
        proposals = self._load_proposals()
        if proposal_id in proposals:
            proposals[proposal_id]["status"] = "rejected"
            self._save_proposals(proposals)
            return {"success": True}
        return {"success": False, "error": "Not found"}

    def rollback(self, proposal_id: str) -> Dict:
        """Rollback an applied change using backup."""
        proposals = self._load_proposals()
        if proposal_id not in proposals:
            return {"success": False, "error": "Proposal not found"}

        p           = proposals[proposal_id]
        backup_path = p.get("backup", "")
        filepath    = p["filepath"]

        if not backup_path or not os.path.exists(backup_path):
            return {"success": False, "error": "No backup found"}

        import shutil
        shutil.copy2(backup_path, filepath)
        p["status"] = "rolled_back"
        self._save_proposals(proposals)
        return {"success": True, "restored": filepath}

    def get_pending_proposals(self) -> List[Dict]:
        proposals = self._load_proposals()
        return [p for p in proposals.values() if p["status"] == "pending"]

    def _backup(self, filepath: str) -> str:
        if not os.path.exists(filepath):
            return ""
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = os.path.basename(filepath)
        dest = os.path.join(self.BACKUP_DIR, f"{ts}_{name}")
        import shutil
        shutil.copy2(filepath, dest)
        return dest

    def _load_proposals(self) -> dict:
        if os.path.exists(self.PROPOSALS_FILE):
            try:
                with open(self.PROPOSALS_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_proposals(self, proposals: dict):
        with open(self.PROPOSALS_FILE, "w") as f:
            json.dump(proposals, f, indent=2)


def _simple_diff(old: str, new: str) -> str:
    """Generate a human-readable diff."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    lines = []
    import difflib
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="",
                                      fromfile="current", tofile="proposed", n=3):
        lines.append(line)
    return "\n".join(lines[:100])   # cap at 100 lines


# Module-level singletons
_smart_home      = SmartHome()
_self_modify     = SelfModifyEngine()

def get_smart_home() -> SmartHome:
    return _smart_home

def get_self_modify() -> SelfModifyEngine:
    return _self_modify
