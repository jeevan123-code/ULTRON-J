"""
autonomous_builder.py — Fully Autonomous Project Builder for Ultron-J ULTIMATE.

Replaces the manual "open Claude.ai and copy-paste" flow.
Ultron generates code, saves files, runs the project, and self-corrects on errors.

Usage:
    from autonomous_builder import AutonomousBuilder, build_project_from_voice
    result = build_project_from_voice("build me a snake game in Python")
"""

import os
import json
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_WORK_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "Ultron_Projects")

# Max self-correction attempts before giving up
MAX_SELF_CORRECT = 3


class AutonomousBuilder:
    def __init__(self, project_type: str, description: str):
        self.project_type = project_type
        self.description  = description
        self.project_name = f"{project_type.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.project_dir  = os.path.join(_WORK_DIR, self.project_name)
        self.files_created = []
        self.error_log    = []

    def build_and_run(self) -> dict:
        """Main autonomous loop: Generate → Save → Run → Self-Correct."""
        os.makedirs(self.project_dir, exist_ok=True)

        # Step 1: Generate code
        code_files = self._generate_code()
        if not code_files:
            return {"success": False, "error": "LLM failed to generate code. Check your API keys."}

        # Step 2: Save files
        for filename, content in code_files.items():
            filepath = os.path.join(self.project_dir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self.files_created.append(filepath)

        # Step 3: Install requirements if present
        req_file = os.path.join(self.project_dir, "requirements.txt")
        if os.path.exists(req_file):
            self._install_requirements(req_file)

        # Step 4: Find and run main file
        main_file = self._find_main_file(code_files.keys())
        if not main_file:
            return {
                "success": True,
                "message": f"Built {self.project_name} but couldn't find a runnable entry point.",
                "dir": self.project_dir,
                "files": list(code_files.keys()),
            }

        # Step 5: Run with self-correction loop
        for attempt in range(1, MAX_SELF_CORRECT + 1):
            run_result = self._run_python_file(os.path.join(self.project_dir, main_file))
            if run_result["success"]:
                return {
                    "success": True,
                    "message": f"Successfully built and ran '{self.project_name}'!",
                    "dir": self.project_dir,
                    "files": list(code_files.keys()),
                    "output": run_result.get("output", ""),
                    "attempts": attempt,
                }
            else:
                if attempt < MAX_SELF_CORRECT:
                    # Self-correct: ask LLM to fix the error
                    fixed_files = self._self_correct(code_files, run_result.get("error", ""))
                    if fixed_files:
                        code_files = fixed_files
                        for filename, content in fixed_files.items():
                            filepath = os.path.join(self.project_dir, filename)
                            with open(filepath, "w", encoding="utf-8") as f:
                                f.write(content)

        return {
            "success": False,
            "message": f"Built '{self.project_name}' but couldn't fix runtime errors after {MAX_SELF_CORRECT} attempts.",
            "dir": self.project_dir,
            "error": run_result.get("error", ""),
            "files": list(code_files.keys()),
        }

    def _generate_code(self) -> dict:
        """Ask LLM to generate project files as JSON."""
        from llm_engine import call_llm_batch, determine_best_provider

        prompt = f"""You are an expert software developer. Build a complete, working {self.project_type}.
Description: {self.description}

Respond ONLY with a valid JSON object where keys are filenames and values are file contents.
Include ALL necessary files. Make the code complete and runnable immediately.
For Python games, use pygame. For web apps, use plain HTML/CSS/JS if possible.
Example format:
{{
    "main.py": "# complete working code here",
    "requirements.txt": "pygame\\n"
}}

IMPORTANT: Respond with ONLY the raw JSON. No markdown, no backticks, no explanation."""

        provider = determine_best_provider(prompt)
        response = call_llm_batch(prompt, provider=provider)

        if not response:
            return {}

        # Strip markdown fences if LLM added them
        response = response.strip()
        response = re.sub(r"^```(?:json)?\s*", "", response)
        response = re.sub(r"\s*```$", "", response)

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
            return {}

    def _self_correct(self, original_files: dict, error_text: str) -> dict:
        """Ask LLM to fix code based on error output."""
        from llm_engine import call_llm_batch, determine_best_provider

        code_summary = "\n\n".join(
            f"=== {fname} ===\n{content}"
            for fname, content in list(original_files.items())[:3]  # limit context
        )

        prompt = f"""The following code produced an error. Fix it.

ERROR:
{error_text[:2000]}

CODE:
{code_summary[:3000]}

Respond ONLY with a valid JSON object with the fixed files (same format as before).
Fix ALL errors. Make it run without any issues."""

        provider = determine_best_provider(prompt)
        response = call_llm_batch(prompt, provider=provider)

        if not response:
            return {}

        response = response.strip()
        response = re.sub(r"^```(?:json)?\s*", "", response)
        response = re.sub(r"\s*```$", "", response)

        try:
            return json.loads(response)
        except Exception:
            return {}

    def _find_main_file(self, filenames) -> str:
        """Find the main entry point file."""
        priority = ["main.py", "app.py", "game.py", "run.py", "index.py", "start.py"]
        filenames = list(filenames)
        for pf in priority:
            if pf in filenames:
                return pf
        # Fallback: first .py file
        for f in filenames:
            if f.endswith(".py") and "requirements" not in f.lower():
                return f
        return ""

    def _install_requirements(self, req_file: str):
        """Install pip requirements silently."""
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", req_file, "-q"],
                timeout=120,
                capture_output=True,
            )
        except Exception:
            pass

    def _run_python_file(self, filepath: str) -> dict:
        """Run a Python file and return output/error."""
        try:
            result = subprocess.run(
                [sys.executable, filepath],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=os.path.dirname(filepath),
            )
            if result.returncode == 0:
                return {"success": True, "output": result.stdout[:2000]}
            else:
                return {
                    "success": False,
                    "error":   (result.stderr or result.stdout)[:2000],
                }
        except subprocess.TimeoutExpired:
            # Games/GUIs run indefinitely — that's OK
            return {"success": True, "output": "Running (GUI/game started in background)"}
        except Exception as e:
            return {"success": False, "error": str(e)}


def build_project_from_voice(command: str) -> dict:
    """
    Parse a voice/text command like 'build me a snake game in python'
    and run the full autonomous build pipeline.
    """
    command_lower = command.lower()

    # Detect project type
    project_types = {
        "snake game":   "snake_game",
        "chess game":   "chess_game",
        "calculator":   "calculator_app",
        "todo app":     "todo_app",
        "weather app":  "weather_app",
        "web scraper":  "web_scraper",
        "chatbot":      "chatbot",
        "quiz game":    "quiz_game",
        "flappy bird":  "flappy_bird_game",
        "pong game":    "pong_game",
        "clicker game": "clicker_game",
        "music player": "music_player",
        "file manager": "file_manager",
        "budget tracker": "budget_tracker",
    }

    detected_type = "python_project"
    for keyword, ptype in project_types.items():
        if keyword in command_lower:
            detected_type = ptype
            break

    builder = AutonomousBuilder(
        project_type=detected_type,
        description=command,
    )
    return builder.build_and_run()
