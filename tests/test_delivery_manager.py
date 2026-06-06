"""Tests for delivery_manager — routing ResearchReport to voice + visual card."""
from unittest.mock import patch, MagicMock
import json

import delivery_manager as dm
from research_types import (
    ResearchReport, DeliveryEnvelope, CitedFact, SourceTier,
    report_from_research_dict,
)
from tests.fixtures.research_responses import wheat_rust_report


def _make_report():
    return report_from_research_dict("wheat leaf rust", wheat_rust_report())


def test_card_payload_shape():
    report = _make_report()
    payload = dm.build_card_payload(report)
    assert payload["query"] == "wheat leaf rust"
    assert isinstance(payload["bullets"], list) and len(payload["bullets"]) >= 1
    assert isinstance(payload["sources"], list)
    for s in payload["sources"]:
        assert "url" in s and "title" in s and "tier" in s


def test_voice_speak_uses_voice_engine_when_route_voice_true():
    report = _make_report()
    env = DeliveryEnvelope(report=report, route_voice=True, route_card=False)
    with patch.object(dm, "_speak", new=MagicMock()) as mock_speak:
        result = dm.deliver(env)
    mock_speak.assert_called_once()
    spoken_arg = mock_speak.call_args[0][0]
    assert isinstance(spoken_arg, str)
    assert "[1]" not in spoken_arg
    assert result["spoken"] is True
    assert result["card"] is None


def test_voice_skipped_when_route_voice_false():
    report = _make_report()
    env = DeliveryEnvelope(report=report, route_voice=False, route_card=True)
    with patch.object(dm, "_speak", new=MagicMock()) as mock_speak:
        result = dm.deliver(env)
    mock_speak.assert_not_called()
    assert result["spoken"] is False
    assert result["card"] is not None


def test_voice_failure_does_not_propagate():
    """If voice_engine fails, delivery still returns the card payload."""
    report = _make_report()
    env = DeliveryEnvelope(report=report, route_voice=True, route_card=True)
    with patch.object(dm, "_speak", side_effect=RuntimeError("tts down")):
        result = dm.deliver(env)
    assert result["spoken"] is False
    assert result["card"] is not None
