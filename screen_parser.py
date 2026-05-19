"""
screen_parser.py — OmniParser integration for Ultron-J.
Provides click-by-intent: find UI elements by description and click them.

OmniParser (microsoft/OmniParser) is not on PyPI — requires manual install.
OMNIPARSER_AVAILABLE is False until OmniParser is installed.
All functions degrade gracefully when unavailable.
"""
import os
from typing import Optional, Tuple

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from omniparser import parse_screen
    OMNIPARSER_AVAILABLE = True
except ImportError:
    OMNIPARSER_AVAILABLE = False


def find_element(
    screenshot_path: str,
    element_description: str,
) -> Optional[Tuple[int, int]]:
    """Find a UI element by description. Returns (x, y) center coords or None."""
    if not OMNIPARSER_AVAILABLE:
        return None
    try:
        with open(screenshot_path, "rb") as f:
            img_bytes = f.read()
        elements = parse_screen(img_bytes)
        query = element_description.lower()
        for el in elements:
            label = el.get("label", "").lower()
            if query in label or label in query:
                bbox = el.get("bbox", [])
                if bbox:
                    return (int((bbox[0] + bbox[2]) / 2), int((bbox[1] + bbox[3]) / 2))
        return None
    except Exception as e:
        print(f"[OmniParser] find_element failed: {e}")
        return None


def click_element(element_description: str) -> dict:
    """Take a screenshot, find element by description, click it."""
    if not OMNIPARSER_AVAILABLE:
        return {
            "success": False,
            "error": "OmniParser not installed. See _upgrade_workspace/task_8_deferred.md",
        }
    try:
        from computer_control import take_screenshot, execute_computer_action
        shot = take_screenshot()
        if not shot.get("success"):
            return {"success": False, "error": "screenshot failed"}
        coords = find_element(shot["path"], element_description)
        if not coords:
            return {"success": False, "error": f"element not found: {element_description}"}
        result = execute_computer_action("click", {"x": coords[0], "y": coords[1]})
        return {"success": True, "coords": coords, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}
