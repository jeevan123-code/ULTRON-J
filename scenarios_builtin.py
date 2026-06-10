"""Phase 4 built-in scenarios — House Party / Get Ready / Bedtime.

`register_builtins()` loads the canonical set into
`multi_device_coordinator`. Caller (typically the voice-engine wiring)
invokes this once at startup behind the ULTRON_PHASE4_ENABLED flag.
"""
from scenario_types import Scenario, ScenarioStep
import multi_device_coordinator as mdc


def _house_party() -> Scenario:
    return Scenario(
        name="house_party",
        trigger_phrases=["house party", "house party protocol", "lockdown mode"],
        steps=[
            ScenarioStep("laptop", "lock"),
            ScenarioStep("phone", "do_not_disturb",
                         {"message": "Going dark — house party protocol active."}),
            ScenarioStep("smart_home", "lights",
                         {"color": "red"}),
            ScenarioStep("smart_home", "lock_doors"),
            ScenarioStep("tv", "security_view"),
        ],
    )


def _get_ready_for_call() -> Scenario:
    return Scenario(
        name="get_ready_for_call",
        trigger_phrases=[
            "get me ready for the call",
            "get me ready for a call",
            "prep for the call",
        ],
        steps=[
            ScenarioStep("laptop", "open_app", {"name": "zoom"}),
            ScenarioStep("phone", "do_not_disturb",
                         {"message": "On a call — phone silenced."}),
            ScenarioStep("smart_home", "lights", {"color": "warm_white"}),
        ],
    )


def _bedtime() -> Scenario:
    return Scenario(
        name="bedtime",
        trigger_phrases=["bedtime", "good night jarvis", "going to sleep"],
        steps=[
            ScenarioStep("smart_home", "lights_off"),
            ScenarioStep("phone", "do_not_disturb",
                         {"message": "Bedtime — phone silenced."}),
            ScenarioStep("laptop", "lock"),
        ],
    )


def register_builtins() -> None:
    """Add canonical scenarios to the global coordinator registry."""
    for scenario in (_house_party(), _get_ready_for_call(), _bedtime()):
        mdc.register(scenario)
