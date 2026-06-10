"""Tests for scenario_types — Scenario dataclass + trigger matching."""
import pytest

from scenario_types import Scenario, ScenarioStep


def _step(target="laptop", action="lock", args=None):
    return ScenarioStep(target=target, action=action, args=args or {})


def test_construct_scenario_with_multiple_steps():
    sc = Scenario(
        name="house_party",
        trigger_phrases=["house party", "lockdown"],
        steps=[_step("laptop", "lock"), _step("phone", "silence"), _step("smart_home", "lights", {"color": "red"})],
    )
    assert sc.name == "house_party"
    assert len(sc.steps) == 3
    assert sc.steps[2].args["color"] == "red"


def test_scenario_to_dict_roundtrip():
    sc = Scenario(
        name="bedtime",
        trigger_phrases=["bedtime"],
        steps=[_step("laptop", "lock"), _step("smart_home", "lights_off")],
    )
    d = sc.to_dict()
    back = Scenario.from_dict(d)
    assert back == sc


def test_matches_trigger_exact_phrase():
    sc = Scenario(name="x", trigger_phrases=["house party"], steps=[])
    assert sc.matches_trigger("house party") is True


def test_matches_trigger_case_insensitive():
    sc = Scenario(name="x", trigger_phrases=["House Party"], steps=[])
    assert sc.matches_trigger("HOUSE party") is True
    assert sc.matches_trigger("house PARTY") is True


def test_matches_trigger_substring():
    sc = Scenario(name="x", trigger_phrases=["house party"], steps=[])
    assert sc.matches_trigger("Jarvis, time for a house party tonight") is True


def test_matches_trigger_no_match_returns_false():
    sc = Scenario(name="x", trigger_phrases=["bedtime"], steps=[])
    assert sc.matches_trigger("good morning") is False
