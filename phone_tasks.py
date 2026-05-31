"""
phone_tasks.py — PhoneBridge: Android control via ADB.
Extracted from task_orchestrator.py to keep that file manageable.
"""
import os
import json
import subprocess
import re
from typing import Dict

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class PhoneBridge:
    """
    Control your Android phone via ADB — USB cable OR wireless WiFi.

    WIRELESS SETUP (no USB needed after first time):
      1. Connect phone via USB once
      2. Call: POST /phone/connect_wireless   (auto-enables TCP/IP on phone)
      3. Disconnect USB — Ultron connects via WiFi from now on
      4. Phone IP is auto-detected and saved to phone_ip.json

    USB SETUP:
      1. Enable USB Debugging: Settings → Developer Options → USB Debugging
      2. Connect USB cable
      3. Run: adb devices  (should show your phone)
    """

    _phone_ip_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phone_ip.json")
    _adb_port      = 5555

    @classmethod
    def _load_saved_ip(cls) -> str:
        try:
            if os.path.exists(cls._phone_ip_file):
                with open(cls._phone_ip_file) as f:
                    data = json.load(f)
                return data.get("ip", "")
        except Exception:
            pass
        return ""

    @classmethod
    def _save_ip(cls, ip: str):
        try:
            import datetime
            with open(cls._phone_ip_file, "w") as f:
                json.dump({"ip": ip, "port": cls._adb_port, "saved_at": str(datetime.datetime.now())}, f)
        except Exception:
            pass

    @classmethod
    def _get_phone_ip_from_usb(cls) -> str:
        """Auto-detect phone IP address via ADB shell (when USB connected)."""
        try:
            cmds = [
                ["adb", "shell", "ip", "route"],
                ["adb", "shell", "ip", "addr", "show", "wlan0"],
                ["adb", "shell", "ifconfig", "wlan0"],
            ]
            for cmd in cmds:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout:
                    matches = re.findall(r"\b(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.\d+\.\d+\.\d+)\b", r.stdout)
                    for m in matches:
                        if not m.endswith(".0") and not m.endswith(".255"):
                            return m
        except Exception:
            pass
        return ""

    @classmethod
    def enable_wireless(cls) -> Dict:
        """Enable wireless ADB on the phone (USB must be connected for first-time setup)."""
        try:
            r = subprocess.run(["adb", "tcpip", str(cls._adb_port)],
                                capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                return {"success": False, "error": f"tcpip failed: {r.stderr}. Is USB connected?"}

            import time
            time.sleep(2)

            ip = cls._get_phone_ip_from_usb()
            if not ip:
                return {
                    "success": False,
                    "error": "Could not detect phone IP. Make sure phone is on same WiFi as laptop.",
                }

            r2 = subprocess.run(["adb", "connect", f"{ip}:{cls._adb_port}"],
                                 capture_output=True, text=True, timeout=10)
            if "connected" in r2.stdout.lower() or "already connected" in r2.stdout.lower():
                cls._save_ip(ip)
                return {
                    "success": True,
                    "ip": ip,
                    "port": cls._adb_port,
                    "message": f"Wireless ADB connected at {ip}:{cls._adb_port}. You can now unplug USB!",
                }
            return {"success": False, "error": f"Connect failed: {r2.stdout} {r2.stderr}"}
        except FileNotFoundError:
            return {"success": False, "error": "ADB not found. Install ADB: https://developer.android.com/tools/adb"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def connect_saved_wireless(cls) -> Dict:
        """Reconnect to phone using saved IP (after USB was removed)."""
        ip = cls._load_saved_ip()
        if not ip:
            return {"success": False, "error": "No saved phone IP. Connect USB first and call enable_wireless."}
        try:
            r = subprocess.run(["adb", "connect", f"{ip}:{cls._adb_port}"],
                                capture_output=True, text=True, timeout=10)
            if "connected" in r.stdout.lower() or "already connected" in r.stdout.lower():
                return {"success": True, "ip": ip, "message": f"Reconnected wirelessly to {ip}"}
            return {"success": False, "error": f"Could not reconnect to {ip}: {r.stdout}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Modern Android 11+ Wireless Debugging (NO USB cable ever) ───────────
    # The phone displays an IP:pair-port + 6-digit code when "Pair device with
    # pairing code" is tapped. After pairing once, the device stays trusted;
    # subsequent sessions just need `adb connect <ip>:<connect-port>` (a
    # different, dynamic port shown on the Wireless Debugging screen).

    @classmethod
    def pair_modern_wireless(cls, host_port: str, code: str) -> Dict:
        """
        One-time pair with phone using Android 11+ Wireless Debugging.

        Args:
          host_port: e.g. "192.168.1.50:43257" (shown on phone's pair-code screen)
          code:      6-digit pairing code displayed by the phone

        After this succeeds, the phone trusts this laptop permanently. To
        actually use the connection, also call connect_modern_wireless().
        """
        try:
            # `adb pair` reads the code from stdin
            r = subprocess.run(
                ["adb", "pair", host_port],
                input=f"{code}\n",
                capture_output=True, text=True, timeout=20,
            )
            out = (r.stdout + r.stderr).lower()
            if "successfully paired" in out or "paired to" in out:
                return {
                    "success": True,
                    "message": (f"Paired with {host_port}. "
                                "Now call connect_modern_wireless() with the "
                                "OTHER port shown on Wireless Debugging."),
                }
            return {"success": False, "error": f"adb pair failed: {r.stdout.strip()} {r.stderr.strip()}"}
        except FileNotFoundError:
            return {"success": False, "error": "ADB not found. Install android-tools-adb."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def connect_modern_wireless(cls, host_port: str) -> Dict:
        """
        Connect to a previously-paired phone.

        Args:
          host_port: e.g. "192.168.1.50:39847" — the connect port shown on
                     phone's Wireless Debugging screen (changes every session).
        """
        try:
            r = subprocess.run(
                ["adb", "connect", host_port],
                capture_output=True, text=True, timeout=10,
            )
            out = (r.stdout + r.stderr).lower()
            if "connected" in out or "already connected" in out:
                # Save just the IP part so legacy code can still see it
                ip = host_port.split(":")[0]
                cls._save_ip(ip)
                # Also persist the full host:port so we can try it first next time
                try:
                    with open(cls._phone_ip_file, "w") as f:
                        json.dump({
                            "ip":          ip,
                            "host_port":   host_port,
                            "mode":        "modern_wireless",
                        }, f)
                except Exception:
                    pass
                return {"success": True, "host_port": host_port,
                        "message": f"Connected wirelessly to {host_port}."}
            if "failed to authenticate" in out or "no devices" in out:
                return {"success": False, "error":
                        "Not paired yet. Run pair_modern_wireless() first."}
            return {"success": False, "error": f"Connect failed: {r.stdout.strip()} {r.stderr.strip()}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def is_connected(cls) -> bool:
        try:
            result = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True, timeout=5
            )
            lines = [l for l in result.stdout.strip().split("\n")[1:] if l.strip()]
            if any("device" in l for l in lines):
                return True
            saved_ip = cls._load_saved_ip()
            if saved_ip:
                r = subprocess.run(["adb", "connect", f"{saved_ip}:{cls._adb_port}"],
                                   capture_output=True, text=True, timeout=5)
                if "connected" in r.stdout.lower():
                    return True
            return False
        except Exception:
            return False

    @staticmethod
    def take_screenshot() -> Dict:
        try:
            out_path = os.path.join(_BASE_DIR, "phone_screenshot.png")
            subprocess.run(["adb", "shell", "screencap", "-p", "/sdcard/screenshot.png"],
                           capture_output=True, timeout=10)
            subprocess.run(["adb", "pull", "/sdcard/screenshot.png", out_path],
                           capture_output=True, timeout=10)
            if os.path.exists(out_path):
                return {"success": True, "path": out_path, "message": "Phone screenshot saved!"}
            return {"success": False, "error": "Screenshot not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def open_app(package_name: str) -> Dict:
        """Open app by package name (e.g. com.whatsapp)."""
        APP_PACKAGES = {
            "whatsapp":  "com.whatsapp",
            "youtube":   "com.google.android.youtube",
            "chrome":    "com.android.chrome",
            "camera":    "com.android.camera2",
            "settings":  "com.android.settings",
            "spotify":   "com.spotify.music",
            "instagram": "com.instagram.android",
            "gmail":     "com.google.android.gm",
            "maps":      "com.google.android.apps.maps",
            "photos":    "com.google.android.apps.photos",
        }
        pkg = APP_PACKAGES.get(package_name.lower(), package_name)
        try:
            subprocess.run(
                ["adb", "shell", "monkey", "-p", pkg, "-c",
                 "android.intent.category.LAUNCHER", "1"],
                capture_output=True, timeout=10,
            )
            return {"success": True, "message": f"Opened {package_name} on phone"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def send_text(text: str) -> Dict:
        """Type text on phone (useful for sending messages)."""
        try:
            escaped = text.replace(" ", "%s").replace("'", "\\'")
            subprocess.run(
                ["adb", "shell", "input", "text", escaped],
                capture_output=True, timeout=10,
            )
            return {"success": True, "message": f"Typed: {text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def press_back() -> Dict:
        try:
            subprocess.run(["adb", "shell", "input", "keyevent", "4"],
                           capture_output=True, timeout=5)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def swipe(direction: str = "up") -> Dict:
        swipes = {
            "up":    ("500", "1500", "500", "300"),
            "down":  ("500", "300", "500", "1500"),
            "left":  ("1000", "800", "100", "800"),
            "right": ("100", "800", "1000", "800"),
        }
        coords = swipes.get(direction.lower(), swipes["up"])
        try:
            subprocess.run(
                ["adb", "shell", "input", "swipe"] + list(coords),
                capture_output=True, timeout=5,
            )
            return {"success": True, "direction": direction}
        except Exception as e:
            return {"success": False, "error": str(e)}
