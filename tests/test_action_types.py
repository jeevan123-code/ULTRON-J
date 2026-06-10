"""Tests for action_types — ActionEvent dataclass + ActionKind enum."""
import pytest

from action_types import ActionEvent, ActionKind


def test_action_kind_has_expected_members():
    names = {m.name for m in ActionKind}
    expected = {
        "FILE_RENAME", "FILE_OPEN", "APP_LAUNCH",
        "CLICK", "TYPE", "SHORTCUT_FIRE", "OTHER",
    }
    assert expected <= names


def test_action_kind_values_are_lowercase_strings():
    for member in ActionKind:
        assert isinstance(member.value, str)
        assert member.value == member.value.lower()


def test_action_event_construction():
    ev = ActionEvent(
        ts=100.0, kind=ActionKind.FILE_RENAME,
        target="notes.txt", detail={"new_name": "renamed.txt"},
    )
    assert ev.ts == 100.0
    assert ev.kind == ActionKind.FILE_RENAME
    assert ev.target == "notes.txt"
    assert ev.detail["new_name"] == "renamed.txt"


def test_action_event_default_detail_is_empty_dict():
    ev = ActionEvent(ts=1.0, kind=ActionKind.CLICK, target="button")
    assert ev.detail == {}


def test_action_event_to_dict_roundtrip():
    ev = ActionEvent(
        ts=10.0, kind=ActionKind.APP_LAUNCH,
        target="zoom", detail={"args": "-foo"},
    )
    d = ev.to_dict()
    assert d["kind"] == "app_launch"
    back = ActionEvent.from_dict(d)
    assert back == ev


def test_action_event_from_dict_accepts_unknown_kind_as_other():
    ev = ActionEvent.from_dict({
        "ts": 1.0, "kind": "made_up_kind", "target": "x", "detail": {},
    })
    assert ev.kind == ActionKind.OTHER
