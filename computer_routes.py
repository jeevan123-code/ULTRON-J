"""
computer_routes.py - Flask blueprint for /computer/* endpoints.

Extracted from app.py during the Task 2 blueprint split. Behavior is byte-for-byte
identical to the original handlers in app.py (lines 1356-1410); only the
decorator changed from @app.route to @computer_bp.route.

Routes:
  /computer/status      GET   - capability check
  /computer/action      POST  - run a computer_control action
  /computer/screenshot  GET   - take a screenshot (base64)
  /computer/log         GET   - recent action log
  /computer/email       POST  - send an email
"""

from flask import Blueprint, request, jsonify

# Mirror app.py's optional-import pattern so this blueprint degrades gracefully
# when computer_control isn't installable (e.g., headless CI without pyautogui).
try:
    from computer_control import (
        execute_computer_action, get_computer_status,
        get_action_log, take_screenshot, send_email,
    )
    COMPUTER_AVAILABLE = True
except ImportError:
    COMPUTER_AVAILABLE = False
    def execute_computer_action(action, params): return {"success": False, "error": "computer_control not available"}
    def get_computer_status(): return {"enabled": False}
    def get_action_log(n=20): return []
    def take_screenshot(): return {"success": False}
    def send_email(to, subject, body): return {"success": False}


computer_bp = Blueprint("computer", __name__)


@computer_bp.route("/computer/status", methods=["GET"])
def computer_status():
    """Check computer control capabilities."""
    return jsonify(get_computer_status())


@computer_bp.route("/computer/action", methods=["POST"])
def computer_action():
    """
    Execute a computer action.
    Body: {"action": "click|type|screenshot|open_url|...", "params": {...}}
    """
    if not COMPUTER_AVAILABLE:
        return jsonify({"success": False, "error": "Install pyautogui: pip install pyautogui pillow"}), 503
    data   = request.json or {}
    action = data.get("action", "").strip()
    params = data.get("params", {})
    if not action:
        return jsonify({"success": False, "error": "action required"}), 400
    result = execute_computer_action(action, params)
    return jsonify(result)


@computer_bp.route("/computer/screenshot", methods=["GET"])
def computer_screenshot():
    """Take a screenshot and return base64 image."""
    if not COMPUTER_AVAILABLE:
        return jsonify({"success": False, "error": "Computer control not available"}), 503
    result = take_screenshot()
    return jsonify(result)


@computer_bp.route("/computer/log", methods=["GET"])
def computer_action_log():
    """Recent computer actions log."""
    n = int(request.args.get("n", 20))
    return jsonify({"log": get_action_log(n)})


@computer_bp.route("/computer/email", methods=["POST"])
def computer_email():
    """
    Send an email.
    Body: {"to": "...", "subject": "...", "body": "..."}
    """
    if not COMPUTER_AVAILABLE:
        return jsonify({"success": False, "error": "Computer control not available"}), 503
    data = request.json or {}
    to      = data.get("to", "")
    subject = data.get("subject", "")
    body    = data.get("body", "")
    if not all([to, subject, body]):
        return jsonify({"success": False, "error": "to, subject, body all required"}), 400
    result = send_email(to, subject, body)
    return jsonify(result)


@computer_bp.route("/computer/smart_click", methods=["POST"])
def smart_click():
    """Click a UI element by description using OmniParser. POST {element: str}."""
    data = request.json or {}
    element = data.get("element", "").strip()
    if not element:
        return jsonify({"success": False, "error": "element field required"}), 400
    try:
        from screen_parser import click_element
        return jsonify(click_element(element))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
