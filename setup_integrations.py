"""Phase 6 setup CLI — `python -m setup_integrations`.

Walks the user through each Phase 6 integration: prompts for env vars,
writes them idempotently into `.env` (backed up to `.env.bak` first),
then runs `integration_health.all()` and prints PASS/FAIL per integration.
"""
import os
import shutil
from typing import Any, Dict, List, Tuple


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(_BASE_DIR, ".env")


_PROMPTS: List[Tuple[str, Tuple[str, ...]]] = [
    ("Telegram bot",
     ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")),
    ("Home Assistant",
     ("HASS_URL", "HASS_TOKEN")),
    ("NewsAPI",
     ("NEWSAPI_KEY",)),
    ("Alpha Vantage",
     ("ALPHAVANTAGE_KEY",)),
]


def _backup_env() -> None:
    if not os.path.exists(_ENV_PATH):
        return
    bak = _ENV_PATH + ".bak"
    try:
        shutil.copy2(_ENV_PATH, bak)
    except Exception:
        pass


def _read_env_lines() -> List[str]:
    if not os.path.exists(_ENV_PATH):
        return []
    with open(_ENV_PATH) as f:
        return f.read().splitlines()


def _write_env_lines(lines: List[str]) -> None:
    os.makedirs(os.path.dirname(_ENV_PATH), exist_ok=True)
    with open(_ENV_PATH, "w") as f:
        f.write("\n".join(lines))
        if lines and not lines[-1].endswith("\n"):
            f.write("\n")


def _upsert_env_var(key: str, value: str) -> None:
    """Add or replace KEY=VALUE in .env. Backs up existing file first."""
    if not key:
        return
    _backup_env()
    lines = _read_env_lines()
    replaced = False
    new_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"{key}={value}")
    _write_env_lines(new_lines)


def _prompt_input(label: str) -> str:
    try:
        return input(f"  {label}: ").strip()
    except EOFError:
        return ""


def run_all(interactive: bool = True) -> Dict[str, Any]:
    """Run the setup flow. Returns the integration_health.all() result."""
    print("\n=== ULTRON Phase 6 — Integration Setup ===\n")
    for label, env_vars in _PROMPTS:
        print(f"-- {label} --")
        for var in env_vars:
            value = _prompt_input(var) if interactive else ""
            if value:
                _upsert_env_var(var, value)
                os.environ[var] = value
                print(f"  saved {var}")
            else:
                print(f"  skipped {var}")
        print("")

    print("Running health checks...\n")
    import integration_health
    results = integration_health.all()
    for name, res in results.items():
        status = "PASS" if res.get("ok") else (
            "NOT CONFIGURED" if not res.get("configured") else "FAIL"
        )
        err = f" — {res.get('error')}" if res.get("error") else ""
        print(f"  [{status}] {name}{err}")
    print("")
    return results


def main() -> None:
    run_all(interactive=True)


if __name__ == "__main__":
    main()
