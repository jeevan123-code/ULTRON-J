"""
app_additions.py — New routes and startup hooks to add to app.py
for Ultron-J BEYOND JARVIS.

How to integrate:
1. In app.py, add at the top:
       from app_additions import register_beyond_jarvis_routes, start_beyond_jarvis
2. After `app = Flask(__name__)` line:
       register_beyond_jarvis_routes(app)
3. In your `if __name__ == "__main__":` block (before app.run):
       start_beyond_jarvis(app)

That's it. All new features are live.
"""

import json
import os
import threading
from datetime import datetime
from flask import Flask, request, jsonify, send_file

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Lazy imports (so missing deps don't crash app.py) ─────────────────────────

def _try_import(module, *names):
    try:
        mod = __import__(module)
        if names:
            return tuple(getattr(mod, n, None) for n in names)
        return mod
    except ImportError:
        return tuple(None for _ in names) if names else None


def register_beyond_jarvis_routes(app: Flask):
    """Register all BEYOND JARVIS endpoints on the Flask app."""

    # ── Plugin System ─────────────────────────────────────────────────────────

    @app.route("/plugins", methods=["GET"])
    def list_plugins_route():
        from plugin_registry import list_plugins, get_plugin_stats
        return jsonify({"plugins": list_plugins(), "stats": get_plugin_stats()})

    @app.route("/plugins/run", methods=["POST"])
    def run_plugin_route():
        from plugin_registry import run_plugin
        data = request.json or {}
        name   = data.get("name", "")
        params = data.get("params", {})
        if not name:
            return jsonify({"success": False, "error": "name required"}), 400
        return jsonify(run_plugin(name, params))

    @app.route("/plugins/create", methods=["POST"])
    def create_plugin_route():
        from plugin_registry import create_plugin_from_llm
        data = request.json or {}
        name  = data.get("name", "")
        desc  = data.get("description", "")
        if not name or not desc:
            return jsonify({"success": False, "error": "name and description required"}), 400
        # Use Ultron's LLM to write the plugin
        try:
            from llm_engine import stream_llm
            def llm_call(prompt):
                result = []
                for chunk in stream_llm(prompt, provider="auto"):
                    result.append(chunk)
                return "".join(result)
            return jsonify(create_plugin_from_llm(name, desc, llm_call))
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ── Autonomous Browser ────────────────────────────────────────────────────

    @app.route("/browse", methods=["POST"])
    def browse_route():
        from autonomous_browser import browse
        data = request.json or {}
        url  = data.get("url", "")
        if not url:
            return jsonify({"success": False, "error": "url required"}), 400
        return jsonify(browse(url, js=data.get("js", False)))

    @app.route("/research", methods=["POST"])
    def research_route():
        from autonomous_browser import research
        data  = request.json or {}
        query = data.get("query", "")
        if not query:
            return jsonify({"success": False, "error": "query required"}), 400
        result = research(query, max_pages=data.get("max_pages", 3))
        return jsonify(result)

    @app.route("/watch_page", methods=["POST"])
    def watch_page_route():
        from autonomous_browser import watch_page
        from mobile_bridge import alert as mobile_alert
        data    = request.json or {}
        url     = data.get("url", "")
        keyword = data.get("keyword", "")
        if not url or not keyword:
            return jsonify({"success": False, "error": "url and keyword required"}), 400

        def on_found(url, text):
            mobile_alert(f"🔔 Keyword '{keyword}' found on {url}", priority="high")

        return jsonify(watch_page(url, keyword,
                                   interval=data.get("interval", 300),
                                   callback=on_found))

    # ── Screen Engine ─────────────────────────────────────────────────────────

    @app.route("/screen/ocr", methods=["GET"])
    def screen_ocr_route():
        from screen_engine import ocr_screen
        return jsonify(ocr_screen())

    @app.route("/screen/screenshot", methods=["GET"])
    def screen_screenshot_route():
        from screen_engine import take_screenshot
        import tempfile
        img = take_screenshot(save=False)
        if img is None:
            return jsonify({"success": False, "error": "Screenshot failed"}), 500
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        img.save(tmp.name, "JPEG", quality=80)
        return send_file(tmp.name, mimetype="image/jpeg")

    @app.route("/screen/errors", methods=["GET"])
    def screen_errors_route():
        from screen_engine import detect_errors_on_screen
        return jsonify(detect_errors_on_screen())

    @app.route("/screen/status", methods=["GET"])
    def screen_status_route():
        from screen_engine import get_screen_status
        return jsonify(get_screen_status())

    @app.route("/screen/analyze", methods=["POST"])
    def screen_analyze_route():
        from screen_engine import analyze_screen_with_vision
        from llm_engine import call_llm_vision
        data   = request.json or {}
        prompt = data.get("prompt", None)
        def vision_fn(b64, prompt):
            return call_llm_vision(b64, prompt)
        return jsonify(analyze_screen_with_vision(vision_fn, prompt))

    # ── Interrupt ─────────────────────────────────────────────────────────────

    @app.route("/voice/interrupt", methods=["POST"])
    def interrupt_route():
        from interrupt_engine import interrupt_speech, is_ultron_speaking
        was_speaking = is_ultron_speaking()
        interrupt_speech()
        return jsonify({"success": True, "was_speaking": was_speaking})

    @app.route("/voice/status", methods=["GET"])
    def voice_status_ext_route():
        from interrupt_engine import is_ultron_speaking
        return jsonify({"speaking": is_ultron_speaking()})

    # ── Long Document Reasoning ────────────────────────────────────────────────

    @app.route("/analyze_document", methods=["POST"])
    def analyze_document_route():
        from interrupt_engine import make_long_doc_reasoner
        data     = request.json or {}
        question = data.get("question", "")
        text     = data.get("text", "")
        filepath = data.get("filepath", "")

        if not text and not filepath:
            return jsonify({"success": False, "error": "text or filepath required"}), 400

        try:
            from llm_engine import stream_llm

            def llm_call(system, user):
                results = []
                for chunk in stream_llm(user, system_prompt=system, provider="auto"):
                    results.append(chunk)
                return "".join(results)

            reasoner = make_long_doc_reasoner(llm_call)
            source   = filepath if filepath else text
            if question:
                result = reasoner.ask(source, question)
            else:
                result = reasoner.summarize(source)
            return jsonify(result)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ── Image Generation ──────────────────────────────────────────────────────

    @app.route("/generate_image", methods=["POST"])
    def generate_image_route():
        from image_gen import generate_image
        data   = request.json or {}
        prompt = data.get("prompt", "")
        if not prompt:
            return jsonify({"success": False, "error": "prompt required"}), 400
        result = generate_image(prompt, size=data.get("size"), prefer=data.get("prefer", "auto"))
        return jsonify(result)

    @app.route("/generated_images", methods=["GET"])
    def list_images_route():
        from image_gen import list_generated_images
        return jsonify({"images": list_generated_images()})

    # ── Smart Home ────────────────────────────────────────────────────────────

    @app.route("/home/command", methods=["POST"])
    def home_command_route():
        from smart_home import get_smart_home
        data    = request.json or {}
        command = data.get("command", "")
        if command:
            return jsonify(get_smart_home().natural_command(command))
        entity = data.get("entity", "")
        action = data.get("action", "")
        sh     = get_smart_home()
        if action == "on":
            return jsonify(sh.turn_on(entity))
        elif action == "off":
            return jsonify(sh.turn_off(entity))
        elif action == "toggle":
            return jsonify(sh.toggle(entity))
        return jsonify({"success": False, "error": "command or entity+action required"}), 400

    @app.route("/home/status", methods=["GET"])
    def home_status_route():
        from smart_home import get_smart_home
        sh = get_smart_home()
        return jsonify({**sh.get_status(), "summary": sh.get_summary()})

    @app.route("/home/devices", methods=["GET"])
    def home_devices_route():
        from smart_home import get_smart_home
        sh = get_smart_home()
        return jsonify({
            "lights":   sh.hass.get_lights(),
            "climate":  sh.hass.get_climate(),
            "switches": sh.hass.get_switches(),
        })

    # ── Self-Modification ─────────────────────────────────────────────────────

    @app.route("/self_modify/propose", methods=["POST"])
    def self_modify_propose_route():
        from smart_home import get_self_modify
        data    = request.json or {}
        fpath   = data.get("filepath", "")
        content = data.get("new_content", "")
        reason  = data.get("reason", "")
        if not fpath or not content:
            return jsonify({"success": False, "error": "filepath and new_content required"}), 400
        return jsonify(get_self_modify().propose_change(fpath, content, reason))

    @app.route("/self_modify/proposals", methods=["GET"])
    def self_modify_list_route():
        from smart_home import get_self_modify
        return jsonify({"proposals": get_self_modify().get_pending_proposals()})

    @app.route("/self_modify/apply/<proposal_id>", methods=["POST"])
    def self_modify_apply_route(proposal_id):
        from smart_home import get_self_modify
        return jsonify(get_self_modify().apply_proposal(proposal_id))

    @app.route("/self_modify/rollback/<proposal_id>", methods=["POST"])
    def self_modify_rollback_route(proposal_id):
        from smart_home import get_self_modify
        return jsonify(get_self_modify().rollback(proposal_id))

    # ── Mobile Bridge Status ──────────────────────────────────────────────────

    @app.route("/mobile/status", methods=["GET"])
    def mobile_status_route():
        from mobile_bridge import get_status as mobile_get_status
        return jsonify(mobile_get_status())

    @app.route("/mobile/alert", methods=["POST"])
    def mobile_alert_route():
        from mobile_bridge import alert as mobile_alert
        data = request.json or {}
        msg  = data.get("message", "")
        if msg:
            mobile_alert(msg, data.get("priority", "normal"))
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "message required"}), 400

    # ── Memory Vault Status ───────────────────────────────────────────────────

    @app.route("/vault/status", methods=["GET"])
    def vault_status_route():
        from memory_vault import vault_status
        return jsonify(vault_status())

    @app.route("/vault/migrate", methods=["POST"])
    def vault_migrate_route():
        from memory_vault import migrate_to_vault
        migrated = migrate_to_vault()
        return jsonify({"success": True, "migrated": migrated})

    print("[BeyondJarvis] All routes registered OK")


# =============================================================================
# STARTUP
# =============================================================================

def start_beyond_jarvis(app: Flask):
    """Start all background services for BEYOND JARVIS mode."""

    def _start_all():
        # Screen monitor
        try:
            from screen_engine import start_screen_monitor
            from mobile_bridge import error_detected_to_phone

            def on_window_change(old, new):
                if new and new != old:
                    print(f"[BeyondJarvis] Window: {old} -> {new}")

            start_screen_monitor(
                interval=3.0,
                on_error_detected=error_detected_to_phone,
                on_window_change=on_window_change,
            )
            print("[BeyondJarvis] Screen monitor started")
        except Exception as e:
            print(f"[BeyondJarvis] Screen monitor skipped: {e}")

        # Telegram mobile bridge
        try:
            from mobile_bridge import start as start_mobile
            started = start_mobile(background=True)
            if started:
                print("[BeyondJarvis] Telegram mobile bridge started")
            else:
                print("[BeyondJarvis] Telegram bridge disabled (no token)")
        except Exception as e:
            print(f"[BeyondJarvis] Mobile bridge skipped: {e}")

        # Plugin watcher
        try:
            from plugin_registry import start_plugin_watcher
            start_plugin_watcher(interval=5)
            print("[BeyondJarvis] Plugin watcher started")
        except Exception as e:
            print(f"[BeyondJarvis] Plugin watcher skipped: {e}")

        print("[BeyondJarvis] BEYOND JARVIS mode ACTIVE")
        print("[BeyondJarvis] New endpoints: /plugins /browse /research /screen/ocr")
        print("[BeyondJarvis]                /generate_image /home/command /analyze_document")
        print("[BeyondJarvis]                /self_modify/* /mobile/* /vault/*")

    t = threading.Thread(target=_start_all, daemon=True, name="beyond_jarvis_init")
    t.start()
