"""Tests for proactive_planner.should_deliver_research_now()."""
from unittest.mock import patch
import proactive_planner as pp


def test_should_deliver_returns_true_when_user_idle():
    with patch.object(pp, "_seconds_since_last_interaction", return_value=120):
        assert pp.should_deliver_research_now() is True


def test_should_deliver_returns_false_when_user_active():
    with patch.object(pp, "_seconds_since_last_interaction", return_value=2):
        assert pp.should_deliver_research_now() is False


def test_should_deliver_respects_custom_quiet_seconds():
    with patch.object(pp, "_seconds_since_last_interaction", return_value=15):
        assert pp.should_deliver_research_now(quiet_seconds=30) is False
        assert pp.should_deliver_research_now(quiet_seconds=10) is True


def test_should_deliver_returns_false_when_seconds_unknown():
    """If we can't tell how long since last interaction, default to NOT interrupting."""
    with patch.object(pp, "_seconds_since_last_interaction", return_value=None):
        assert pp.should_deliver_research_now() is False
