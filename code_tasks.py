"""
code_tasks.py — ProjectBuilder and code-execution helpers.
Extracted from task_orchestrator.py to keep that file manageable.
"""
import os
import re
import time
import webbrowser
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_WORK_DIR  = os.path.join(_BASE_DIR, "workspace")
os.makedirs(_WORK_DIR, exist_ok=True)

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.1
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

try:
    import pyperclip
    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False

# Session-scoped active builders — keyed by session_id
_active_builders: Dict[str, "ProjectBuilder"] = {}


class ProjectBuilder:
    """
    When you say "I want to build X", Ultron:
    1. Asks you clarifying questions
    2. Opens Claude.ai with a perfect prompt
    3. Waits for you to paste code back (or auto-detects clipboard)
    4. Saves the files into a project folder
    5. Runs the project automatically
    """

    CLARIFYING_QUESTIONS = {
        "game": [
            "What type of game? (e.g. 2D arcade, puzzle, RPG, multiplayer)",
            "What language/engine? (Python with pygame, JavaScript browser game, Unity C#, etc.)",
            "Any specific features? (levels, score, sound, multiplayer?)",
        ],
        "app": [
            "Is this a desktop app, web app, or mobile app?",
            "What should the app do exactly?",
            "Any specific look or features you want?",
        ],
        "website": [
            "What kind of website? (portfolio, e-commerce, blog, tool)",
            "HTML/CSS only, or do you want a backend too?",
            "Any specific design style or colors?",
        ],
        "bot": [
            "What platform? (Discord, Telegram, WhatsApp, Twitter/X)",
            "What should the bot do?",
            "Any commands or automation you need?",
        ],
        "script": [
            "What should the script do exactly?",
            "What language? (Python, JavaScript, Bash)",
            "Should it run once or repeatedly?",
        ],
        "tool": [
            "What problem does this tool solve?",
            "Should it have a GUI or run in the terminal?",
            "What language do you prefer?",
        ],
    }

    def __init__(self, project_type: str, description: str):
        self.project_type  = project_type.lower()
        self.description   = description
        self.answers       = {}
        self.project_name  = self._slugify(description)
        self.project_dir   = os.path.join(_WORK_DIR, self.project_name)

    def _slugify(self, text: str) -> str:
        text = re.sub(r"[^\w\s-]", "", text.lower())
        text = re.sub(r"[\s-]+", "_", text).strip("_")
        return text[:40] or "project"

    def get_questions(self) -> List[str]:
        """Return clarifying questions for this project type."""
        for key in self.CLARIFYING_QUESTIONS:
            if key in self.project_type or key in self.description.lower():
                return self.CLARIFYING_QUESTIONS[key]
        return self.CLARIFYING_QUESTIONS.get("script", [
            "What exactly should it do?",
            "Any specific requirements or features?",
        ])

    def build_claude_prompt(self) -> str:
        """Build a detailed prompt to send to Claude."""
        answers_text = ""
        for q, a in self.answers.items():
            answers_text += f"\n- {q}: {a}"

        return f"""Build me a complete, working {self.project_type}: {self.description}

Additional details:{answers_text}

Requirements:
- Write complete, production-ready code (no placeholders)
- Include ALL necessary files
- Add clear comments explaining what each part does
- Include a requirements.txt if Python packages are needed
- Include setup/run instructions as a comment at the top
- Make it actually work when I run it

Please give me all the code files I need, clearly separated with filenames."""

    def open_claude_with_prompt(self, prompt: str) -> Dict:
        """Opens claude.ai in browser and types the prompt automatically."""
        try:
            if CLIP_AVAILABLE:
                pyperclip.copy(prompt)

            webbrowser.open("https://claude.ai/new")
            time.sleep(3)

            if GUI_AVAILABLE and CLIP_AVAILABLE:
                time.sleep(2)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.5)

            return {
                "success": True,
                "message": "Claude.ai opened with your prompt! The prompt was copied to clipboard — paste it if not auto-filled.",
                "prompt":  prompt,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_code_from_clipboard(self) -> Dict:
        """Reads code from clipboard, parses it into files, and saves them."""
        if not CLIP_AVAILABLE:
            return {"success": False, "error": "pyperclip not available"}

        try:
            clipboard_content = pyperclip.paste()
            if not clipboard_content or len(clipboard_content) < 20:
                return {"success": False, "error": "Clipboard is empty or too short"}

            files_saved = self._parse_and_save_code(clipboard_content)
            return {
                "success":     True,
                "files_saved": files_saved,
                "project_dir": self.project_dir,
                "message":     f"Saved {len(files_saved)} file(s) to {self.project_dir}",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parse_and_save_code(self, text: str) -> List[str]:
        """Parse code blocks from Claude's response and save as files."""
        os.makedirs(self.project_dir, exist_ok=True)
        saved_files = []

        pattern1 = re.compile(
            r"```(?:\w+)?\s*\n(?:#\s*filename:\s*(.+?)\n|//\s*(.+?)\n)?(.*?)```",
            re.DOTALL,
        )
        pattern2 = re.compile(
            r"\*\*([^*]+\.\w+)\*\*\s*\n```(?:\w+)?\n(.*?)```",
            re.DOTALL,
        )
        pattern3 = re.compile(
            r"(?:#{1,3}\s*|`?)(\w[\w./\-]+\.\w+)`?\s*\n```(?:\w+)?\n(.*?)```",
            re.DOTALL,
        )

        found = False

        for m in pattern2.finditer(text):
            self._write_file(m.group(1).strip(), m.group(2))
            saved_files.append(m.group(1).strip())
            found = True

        if not found:
            for m in pattern3.finditer(text):
                self._write_file(m.group(1).strip(), m.group(2))
                saved_files.append(m.group(1).strip())
                found = True

        if not found:
            for m in pattern1.finditer(text):
                filename = (m.group(1) or m.group(2) or "").strip()
                code = m.group(3)
                if not filename:
                    filename = f"main{self._detect_extension(code)}"
                self._write_file(filename, code)
                saved_files.append(filename)
                found = True

        if not found:
            ext = self._detect_extension(text)
            filename = f"main{ext}"
            self._write_file(filename, text)
            saved_files.append(filename)

        return saved_files

    def _write_file(self, filename: str, content: str):
        filename = filename.strip().lstrip("/\\")
        filepath = os.path.join(self.project_dir, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content.strip())

    def _detect_extension(self, code: str) -> str:
        if "import pygame" in code or "def " in code or "print(" in code:
            return ".py"
        if "<html" in code.lower():
            return ".html"
        if "function " in code or "const " in code or "let " in code:
            return ".js"
        return ".py"

    def run_project(self) -> Dict:
        """Run the project after code is saved."""
        try:
            main_file = self._find_main_file()
            if not main_file:
                return {"success": False, "error": "No main file found in project folder"}

            ext = Path(main_file).suffix.lower()

            if ext == ".py":
                req_file = os.path.join(self.project_dir, "requirements.txt")
                if os.path.exists(req_file):
                    subprocess.Popen(
                        f'start cmd /k "pip install -r requirements.txt && python {main_file}"',
                        shell=True, cwd=self.project_dir,
                    )
                else:
                    subprocess.Popen(
                        f'start cmd /k "python {main_file}"',
                        shell=True, cwd=self.project_dir,
                    )
            elif ext == ".html":
                webbrowser.open(f"file:///{main_file}")
            elif ext in (".js", ".ts"):
                subprocess.Popen(
                    f'start cmd /k "node {main_file}"',
                    shell=True, cwd=self.project_dir,
                )
            else:
                os.startfile(main_file)

            subprocess.Popen(f'explorer "{self.project_dir}"', shell=True)

            return {
                "success":    True,
                "main_file":  main_file,
                "project_dir": self.project_dir,
                "message":    f"Running {main_file}! Project folder is open.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _find_main_file(self) -> Optional[str]:
        """Find the main runnable file in project directory."""
        priority = ["main.py", "app.py", "game.py", "run.py", "index.html",
                    "index.js", "main.js", "server.py"]
        for name in priority:
            fp = os.path.join(self.project_dir, name)
            if os.path.exists(fp):
                return fp
        for f in Path(self.project_dir).glob("*.py"):
            return str(f)
        for f in Path(self.project_dir).glob("*.html"):
            return str(f)
        for f in Path(self.project_dir).glob("*.js"):
            return str(f)
        return None


def handle_build_answers(session_id: str, answers: List[str]) -> Dict:
    """Called after user answers the clarifying questions."""
    builder = _active_builders.get(session_id)
    if not builder:
        return {"success": False, "error": "No active build session. Start over."}

    questions = builder.get_questions()
    for i, q in enumerate(questions):
        if i < len(answers):
            builder.answers[q] = answers[i]

    prompt = builder.build_claude_prompt()
    result = builder.open_claude_with_prompt(prompt)
    result["action_taken"] = "claude_opened_for_build"
    result["next_step"]    = (
        "Claude.ai is open with your project prompt! "
        "Once Claude gives you the code, say 'save the code' and I'll grab it from clipboard, "
        "organize it into files, and run it for you automatically."
    )
    return result


def save_and_run_from_clipboard(session_id: str) -> Dict:
    """Called when user says 'save the code' or 'run it'."""
    builder = _active_builders.get(session_id)
    if not builder:
        builder = ProjectBuilder(project_type="project", description="clipboard_project")
        _active_builders[session_id] = builder

    save_result = builder.save_code_from_clipboard()
    if not save_result["success"]:
        return save_result

    run_result = builder.run_project()

    return {
        "success":      True,
        "action_taken": "saved_and_running",
        "files_saved":  save_result.get("files_saved", []),
        "project_dir":  builder.project_dir,
        "run_result":   run_result,
        "message": (
            f"Saved {len(save_result.get('files_saved', []))} files to {builder.project_dir}. "
            f"Running the project now! Project folder is open."
        ),
    }
