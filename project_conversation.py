"""
project_conversation.py — Interactive Project Builder Conversation
===================================================================
When you say "I want to build a game", Ultron enters a guided
Q&A mode. This module manages that conversation state.

Flow:
  User: "I want to build a snake game"
  Ultron: "What language? Python, JavaScript, or other?"
  User: "Python with pygame"
  Ultron: "Any special features? (levels, high score, multiplayer?)"
  User: "Just basic with score"
  Ultron: [Opens Claude.ai with perfect prompt, copies it to clipboard]
  User: [Gets code from Claude, says "save the code"]
  Ultron: [Saves files, installs requirements, runs the game]

Add this as a new route in app.py: /project/*
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any

_BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
_STATE_FILE = os.path.join(_BASE_DIR, "project_sessions.json")

# =============================================================================
# SESSION STATE
# =============================================================================

_sessions: Dict[str, Dict] = {}


def _save_sessions():
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump(_sessions, f, indent=2)
    except Exception:
        pass


def _load_sessions():
    global _sessions
    try:
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE) as f:
                _sessions = json.load(f)
    except Exception:
        _sessions = {}


_load_sessions()


# =============================================================================
# PROJECT TEMPLATES — smart questions per project type
# =============================================================================

PROJECT_TEMPLATES = {
    "snake_game": {
        "detect":    ["snake"],
        "type":      "game",
        "language":  "Python (pygame)",
        "questions": [
            ("difficulty", "Easy, Medium, or Hard mode? (affects snake speed)"),
            ("features",   "Any extra features? (wall wrap, levels, high score board, sound?)"),
            ("style",      "Classic green on black, or modern colorful style?"),
        ],
        "auto_prompt": (
            "Build a complete Snake game in Python using pygame.\n"
            "Difficulty: {difficulty}\nFeatures: {features}\nStyle: {style}\n"
            "Include: main.py, requirements.txt (just pygame), and a README with how to run it."
        ),
    },
    "2d_game": {
        "detect":    ["2d game", "2d arcade", "platform", "platformer", "side scroller"],
        "type":      "game",
        "questions": [
            ("language",  "Python (pygame) or JavaScript (browser)?"),
            ("concept",   "What's the game concept? (e.g. dodge enemies, collect coins, shoot asteroids)"),
            ("features",  "Any special features? (levels, power-ups, enemies, boss fight?)"),
        ],
    },
    "web_app": {
        "detect":    ["web app", "website", "web application", "flask app", "django"],
        "type":      "app",
        "questions": [
            ("backend",  "Flask (Python), Node.js, or just HTML/CSS/JS (no backend)?"),
            ("purpose",  "What should the web app do exactly?"),
            ("features", "Any specific pages or features? (login, database, API, dashboard?)"),
        ],
    },
    "discord_bot": {
        "detect":    ["discord bot", "discord"],
        "type":      "bot",
        "questions": [
            ("language", "Python (discord.py) or JavaScript (discord.js)?"),
            ("commands", "What commands should the bot have? (e.g. !help, !meme, moderation, music)"),
            ("features", "Any extra features? (auto-roles, welcome messages, slash commands?)"),
        ],
    },
    "telegram_bot": {
        "detect":    ["telegram bot", "telegram"],
        "type":      "bot",
        "questions": [
            ("commands", "What commands should the bot respond to?"),
            ("features", "Any special features? (buttons, inline mode, media, database?)"),
        ],
    },
    "desktop_app": {
        "detect":    ["desktop app", "gui app", "tkinter", "pyqt", "windows app"],
        "type":      "app",
        "questions": [
            ("purpose",  "What should the app do?"),
            ("gui_lib",  "GUI library? (Tkinter (simple), PyQt5 (modern), CustomTkinter (beautiful))"),
            ("features", "Any specific features? (file open, save, settings, dark mode?)"),
        ],
    },
    "api": {
        "detect":    ["api", "rest api", "fastapi", "backend api"],
        "type":      "script",
        "questions": [
            ("framework", "FastAPI or Flask?"),
            ("endpoints", "What endpoints do you need? (e.g. /users, /products, /auth)"),
            ("database",  "Need a database? (SQLite, PostgreSQL, or none?)"),
        ],
    },
    "automation_script": {
        "detect":    ["automate", "automation", "script", "auto"],
        "type":      "script",
        "questions": [
            ("what",    "What do you want to automate exactly?"),
            ("trigger", "Should it run once, on a schedule, or when triggered?"),
            ("output",  "What should the result be? (file, email, notification, etc.)"),
        ],
    },
    "generic": {
        "detect":    [],
        "type":      "app",
        "questions": [
            ("what",     "What exactly should it do?"),
            ("language", "Any preferred language? (Python, JavaScript, or doesn't matter)"),
            ("features", "Any specific requirements or features?"),
        ],
    },
}


def detect_template(description: str) -> str:
    """Auto-detect the best template from description."""
    dl = description.lower()
    for key, tmpl in PROJECT_TEMPLATES.items():
        if key == "generic":
            continue
        for trigger in tmpl["detect"]:
            if trigger in dl:
                return key
    return "generic"


# =============================================================================
# CONVERSATION MANAGER
# =============================================================================

class ProjectConversation:
    """Manages one project-building conversation session."""

    def __init__(self, session_id: str, description: str):
        self.session_id  = session_id
        self.description = description
        self.template_key = detect_template(description)
        self.template     = PROJECT_TEMPLATES[self.template_key]
        self.answers:  Dict[str, str] = {}
        self.q_index:  int = 0
        self.state:    str = "asking"   # asking | building | saving | done
        self.created_at = datetime.now().isoformat()
        self.files_saved: List[str] = []
        self.project_dir: str = ""

    def current_question(self) -> Optional[Dict]:
        """Return the current question to ask the user."""
        questions = self.template.get("questions", [])
        if self.q_index < len(questions):
            key, text = questions[self.q_index]
            return {"key": key, "text": text, "index": self.q_index, "total": len(questions)}
        return None

    def answer(self, answer_text: str) -> Optional[Dict]:
        """
        Record user's answer to current question.
        Returns next question or None if done.
        """
        questions = self.template.get("questions", [])
        if self.q_index < len(questions):
            key, _ = questions[self.q_index]
            self.answers[key] = answer_text
            self.q_index += 1

        return self.current_question()

    def is_done_asking(self) -> bool:
        return self.q_index >= len(self.template.get("questions", []))

    def build_claude_prompt(self) -> str:
        """Build the final Claude prompt with all answers."""
        # Check if template has auto_prompt
        if "auto_prompt" in self.template:
            try:
                return self.template["auto_prompt"].format(**self.answers)
            except KeyError:
                pass

        # Build dynamic prompt
        answers_block = ""
        for key, val in self.answers.items():
            answers_block += f"\n- {key.replace('_', ' ').title()}: {val}"

        prompt = f"""Build me a complete, working {self.template['type']}: {self.description}

Project details:{answers_block}

Requirements:
- Write COMPLETE, production-ready code — no placeholders, no "add your code here"
- All files needed to run it from scratch
- For Python: include requirements.txt if any pip packages needed
- Add a comment at the top of main file: # HOW TO RUN: (exact command)
- Make it actually WORK when I run it immediately
- Keep code well-commented so I understand it

Output format:
**filename.ext**
```language
(complete code here)
```

Give me ALL files needed."""

        return prompt

    def to_dict(self) -> Dict:
        return {
            "session_id":   self.session_id,
            "description":  self.description,
            "template_key": self.template_key,
            "answers":      self.answers,
            "q_index":      self.q_index,
            "state":        self.state,
            "created_at":   self.created_at,
            "files_saved":  self.files_saved,
            "project_dir":  self.project_dir,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ProjectConversation":
        obj             = cls.__new__(cls)
        obj.session_id  = d["session_id"]
        obj.description = d["description"]
        obj.template_key = d.get("template_key", "generic")
        obj.template    = PROJECT_TEMPLATES.get(obj.template_key, PROJECT_TEMPLATES["generic"])
        obj.answers     = d.get("answers", {})
        obj.q_index     = d.get("q_index", 0)
        obj.state       = d.get("state", "asking")
        obj.created_at  = d.get("created_at", "")
        obj.files_saved = d.get("files_saved", [])
        obj.project_dir = d.get("project_dir", "")
        return obj


# In-memory store
_active_convos: Dict[str, ProjectConversation] = {}


def start_project_conversation(session_id: str, description: str) -> Dict:
    """Start a new project build conversation."""
    convo = ProjectConversation(session_id, description)
    _active_convos[session_id] = convo
    q = convo.current_question()
    return {
        "status":       "started",
        "session_id":   session_id,
        "description":  description,
        "template":     convo.template_key,
        "question":     q["text"] if q else None,
        "q_index":      0,
        "total_q":      len(convo.template.get("questions", [])),
        "message": (
            f"I'll help you build: {description}. "
            f"I have {len(convo.template.get('questions', []))} quick questions "
            f"to create the perfect prompt for Claude."
        ),
    }


def answer_project_question(session_id: str, answer: str) -> Dict:
    """Record answer and return next question or trigger Claude."""
    convo = _active_convos.get(session_id)
    if not convo:
        return {"error": "No active project. Say 'I want to build something' first."}

    next_q = convo.answer(answer)

    if next_q:
        return {
            "status":   "asking",
            "question": next_q["text"],
            "q_index":  next_q["index"],
            "total_q":  next_q["total"],
        }

    # All questions answered — build prompt and open Claude
    import webbrowser, time
    try:
        import pyperclip
        CLIP_OK = True
    except ImportError:
        CLIP_OK = False

    prompt = convo.build_claude_prompt()
    convo.state = "building"

    if CLIP_OK:
        pyperclip.copy(prompt)

    webbrowser.open("https://claude.ai/new")
    time.sleep(3)

    # Try to auto-paste
    try:
        import pyautogui
        time.sleep(2)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        pass

    return {
        "status":  "claude_opened",
        "message": (
            "Claude.ai is open with your complete project prompt! "
            "It was also copied to clipboard. "
            "Once Claude gives you the code, say 'save the code' and I'll save "
            "all files and run the project automatically."
        ),
        "prompt_preview": prompt[:300] + "...",
    }


def save_project_code(session_id: str) -> Dict:
    """Save code from clipboard and run the project."""
    from task_orchestrator import ProjectBuilder, _WORK_DIR

    convo = _active_convos.get(session_id)
    if not convo:
        # Generic save
        builder = ProjectBuilder("project", "clipboard_project")
    else:
        builder = ProjectBuilder(convo.template["type"], convo.description)

    save_result = builder.save_code_from_clipboard()
    if not save_result["success"]:
        return {
            "status":  "error",
            "message": (
                f"Could not read clipboard: {save_result.get('error')}. "
                "Copy the code from Claude first, then say 'save the code'."
            ),
        }

    if convo:
        convo.files_saved = save_result.get("files_saved", [])
        convo.project_dir = builder.project_dir
        convo.state       = "done"

    run_result = builder.run_project()

    return {
        "status":      "done",
        "files_saved": save_result.get("files_saved", []),
        "project_dir": builder.project_dir,
        "running":     run_result.get("success", False),
        "message": (
            f"Saved {len(save_result.get('files_saved', []))} files to your workspace. "
            f"The project folder is open and your {convo.description if convo else 'project'} "
            f"is running!"
        ),
    }


# =============================================================================
# FLASK ROUTES — add these to app.py
# =============================================================================
"""
HOW TO ADD TO app.py:
=====================
Add these imports at the top of app.py:
  from project_conversation import (
      start_project_conversation,
      answer_project_question,
      save_project_code,
  )

Then add these routes:

@app.route("/project/start", methods=["POST"])
def project_start():
    data        = request.json or {}
    description = data.get("description", "").strip()
    session_id  = data.get("session_id", "default")
    if not description:
        return jsonify({"error": "description required"}), 400
    return jsonify(start_project_conversation(session_id, description))

@app.route("/project/answer", methods=["POST"])
def project_answer():
    data       = request.json or {}
    session_id = data.get("session_id", "default")
    answer     = data.get("answer", "").strip()
    return jsonify(answer_project_question(session_id, answer))

@app.route("/project/save", methods=["POST"])
def project_save():
    data       = request.json or {}
    session_id = data.get("session_id", "default")
    return jsonify(save_project_code(session_id))

@app.route("/project/status", methods=["GET"])
def project_status():
    session_id = request.args.get("session_id", "default")
    from project_conversation import _active_convos
    convo = _active_convos.get(session_id)
    if not convo:
        return jsonify({"active": False})
    return jsonify({"active": True, **convo.to_dict()})
"""
