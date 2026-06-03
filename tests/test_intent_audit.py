"""
Phase 2.3 — full 81-pattern intent audit.

For every pattern in intent_router._PATTERNS we provide a sample phrase
and an expected action_type. The test asserts that detect_intent(phrase)
returns that type — catching three classes of bug at once:

  1. A pattern's regex doesn't match the phrasing it was written for
     (typo / wrong character class / forgotten alternative).
  2. An earlier broad pattern shadows a later specific one, so the
     "wrong" type is dispatched for a clearly-intended phrase.
  3. A type with no handler at all — already covered by
     tests/test_capabilities.py::test_every_pattern_has_handler but
     re-confirmed here at the dispatch level.

Where multiple patterns map to the same type (e.g. several `*` phrasings
for read_file), each pattern still gets its own phrase to prove the
specific regex fires, but the assertion is on type — same-type
"shadowing" is fine.

Run:
    venv/bin/python -m pytest tests/test_intent_audit.py -v --timeout=20
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from intent_router import _PATTERNS, detect_intent          # noqa: E402


# ─── (phrase, expected_type) — one row per index in _PATTERNS ─────────────────
# Order MUST match _PATTERNS exactly so a regex change paired with a phrase
# change can be reviewed side-by-side. The id in the parametrize is f"{i:02d}".

SAMPLE_PHRASES: list[tuple[str, str]] = [
    # 00–01 — repeat_last
    ("again",                                "repeat_last"),
    ("repeat that",                          "repeat_last"),

    # 02–04 — help_me_now
    ("help me",                              "help_me_now"),
    ("i'm stuck",                            "help_me_now"),
    ("what do i do now",                     "help_me_now"),

    # 05 — run_script
    ("run script.py",                        "run_script"),

    # 06–08 — read_file (three phrasings)
    ("read notes.txt",                       "read_file"),
    ("show notes.txt",                       "read_file"),
    ("cat notes.txt",                        "read_file"),

    # 09 — write_file
    ("write hello to notes.txt",             "write_file"),

    # 10–11 — append_to_file / edit_file
    ("append hello to notes.txt",            "append_to_file"),
    ("edit notes.txt: new line",             "edit_file"),

    # 12 — find_file_query
    ("find notes.txt",                       "find_file_query"),

    # 13 — delete_folder (must be tested with explicit "folder" word
    # so it doesn't fall through to delete_file)
    ("delete folder backups",                "delete_folder"),

    # 14 — delete_file
    ("delete notes.txt",                     "delete_file"),

    # 15 — rename_file
    ("rename old.txt to new.txt",            "rename_file"),

    # 16 — copy_file
    ("copy notes.txt to backup",             "copy_file"),

    # 17 — move_file
    ("move notes.txt to archive",            "move_file"),

    # 18 — zip_item
    ("zip backups",                          "zip_item"),

    # 19–23 — list_dir (five phrasings)
    ("list files in downloads",              "list_dir"),
    ("list ~/downloads",                     "list_dir"),
    ("list documents",                       "list_dir"),
    ("show files in downloads",              "list_dir"),
    # Pattern 23 requires the qualifier BEFORE the path
    # ("what's in folder X", not "what's in X folder"). The natural-
    # English form "what's in X folder" / "what's in X" is currently
    # unsupported -- noted as a Phase 8 UX proposal in CHANGES.md.
    ("what's in folder downloads",           "list_dir"),

    # 24–27 — create_file_named / create_file_in_dir / create_file_name_only x2
    ("create file notes.txt in downloads",   "create_file_named"),
    ("create file in downloads",             "create_file_in_dir"),
    ("create file notes.txt",                "create_file_name_only"),
    ("make file notes.txt",                  "create_file_name_only"),

    # 28 — open_file (by extension; must precede open_app)
    ("open notes.txt",                       "open_file"),

    # 29 — open_folder
    ("open folder downloads",                "open_folder"),

    # 30 — open_and_play (must precede open_app)
    ("open chrome and play despacito",       "open_and_play"),

    # 31 — open_and_search
    ("open google and search for cats",      "open_and_search"),

    # 32–34 — open_app (three verbs)
    ("open chrome",                          "open_app"),
    ("launch chrome",                        "open_app"),
    ("start chrome",                         "open_app"),

    # 35–39 — get_time (five phrasings)
    ("what's the time",                      "get_time"),
    ("what time is it",                      "get_time"),
    ("what is the time",                     "get_time"),
    ("tell me the time",                     "get_time"),
    ("clock",                                "get_time"),

    # 40–41 — get_date (two phrasings)
    ("what's the date",                      "get_date"),
    ("what day is it",                       "get_date"),

    # 42 — take_screenshot_to
    ("take screenshot save to /tmp/x.png",   "take_screenshot_to"),

    # 43–45 — take_screenshot (three phrasings)
    ("screenshot",                           "take_screenshot"),
    ("take a screencap",                     "take_screenshot"),
    ("capture screen",                       "take_screenshot"),

    # 46–47 — volume_up
    ("volume up",                            "volume_up"),
    ("louder",                               "volume_up"),

    # 48–49 — volume_down
    ("volume down",                          "volume_down"),
    ("quieter",                              "volume_down"),

    # 50 — volume_mute
    ("mute",                                 "volume_mute"),

    # 51 — media_pause
    ("pause",                                "media_pause"),

    # 52 — media_play
    ("resume",                               "media_play"),

    # 53–54 — media_next
    ("next",                                 "media_next"),
    ("skip",                                 "media_next"),

    # 55–56 — media_prev
    ("previous",                             "media_prev"),
    ("go back",                              "media_prev"),

    # 57 — minimize_window
    ("minimize",                             "minimize_window"),

    # 58 — maximize_window
    ("maximize",                             "maximize_window"),

    # 59 — close_window
    ("close window",                         "close_window"),

    # 60 — close_app (broad — must come AFTER close_window)
    ("close chrome",                         "close_app"),

    # 61 — lock_screen
    ("lock screen",                          "lock_screen"),

    # 62 — sleep_computer
    ("sleep",                                "sleep_computer"),

    # 63 — empty_trash
    ("empty trash",                          "empty_trash"),

    # 64 — system_info
    ("system info",                          "system_info"),

    # 65 — brightness_up
    ("brightness up",                        "brightness_up"),

    # 66 — brightness_down
    ("brightness down",                      "brightness_down"),

    # 67 — press_escape
    ("press escape",                         "press_escape"),

    # 68 — press_enter
    ("press enter",                          "press_enter"),

    # 69 — press_tab
    ("press tab",                            "press_tab"),

    # 70 — press_backspace
    ("press backspace",                      "press_backspace"),

    # 71 — press_delete
    ("press delete",                         "press_delete"),

    # 72 — press_space
    ("press space",                          "press_space"),

    # 73 — press_key_name (single-letter / Fn key; must NOT collide with
    # specific press_* patterns above)
    ("press a",                              "press_key_name"),

    # 74 — scroll_down
    ("scroll down",                          "scroll_down"),

    # 75 — scroll_up
    ("scroll up",                            "scroll_up"),

    # 76 — type_text_cmd
    ("type: hello world",                    "type_text_cmd"),

    # 77 — play_media_on
    ("play despacito on spotify",            "play_media_on"),

    # 78 — play_media
    ("play despacito",                       "play_media"),

    # 79 — search_on
    ("search cats on google",                "search_on"),

    # 80 — search_web
    ("search for cats",                      "search_web"),
]


def test_phrase_count_matches_pattern_count():
    """Lock that we have exactly one sample per pattern. If a pattern is
    added or removed, this test fires and forces the audit to be updated."""
    assert len(SAMPLE_PHRASES) == len(_PATTERNS) == 81, (
        f"{len(SAMPLE_PHRASES)} sample phrases vs {len(_PATTERNS)} patterns"
    )


@pytest.mark.parametrize(
    "phrase,expected_type",
    SAMPLE_PHRASES,
    ids=[f"{i:02d}:{p[1]}" for i, p in enumerate(SAMPLE_PHRASES)],
)
def test_phrase_dispatches_to_expected_type(phrase: str, expected_type: str):
    """Every sample phrase must detect to its expected action_type. A
    miss means either (a) the regex is broken for that phrasing, or
    (b) an earlier pattern is shadowing this one."""
    intent = detect_intent(phrase)
    got = intent["type"] if intent else None
    assert got == expected_type, (
        f"{phrase!r} dispatched to {got!r}, expected {expected_type!r}"
    )
