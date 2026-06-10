"""Tests for scenarios_builtin — canonical House Party / Get Ready / Bedtime."""
import pytest

import multi_device_coordinator as mdc
import scenarios_builtin as sb


@pytest.fixture(autouse=True)
def _reset():
    mdc._reset_for_test()
    yield
    mdc._reset_for_test()


def test_register_builtins_adds_canonical_scenarios():
    sb.register_builtins()
    names = {s.name for s in mdc._snapshot_for_test()}
    assert {"house_party", "get_ready_for_call", "bedtime"} <= names


def test_house_party_trigger_matches():
    sb.register_builtins()
    sc = mdc.match_trigger("Jarvis, time for a house party")
    assert sc is not None
    assert sc.name == "house_party"


def test_bedtime_trigger_matches():
    sb.register_builtins()
    sc = mdc.match_trigger("Bedtime, please")
    assert sc is not None
    assert sc.name == "bedtime"


def test_each_builtin_scenario_has_at_least_one_step():
    sb.register_builtins()
    for sc in mdc._snapshot_for_test():
        assert len(sc.steps) >= 1, f"{sc.name} has no steps"


def test_get_ready_for_call_trigger_matches():
    sb.register_builtins()
    sc = mdc.match_trigger("get me ready for the call")
    assert sc is not None
    assert sc.name == "get_ready_for_call"
