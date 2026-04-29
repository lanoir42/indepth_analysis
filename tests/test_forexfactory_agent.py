"""Tests for ForexFactoryAgent."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from bgilib.errors import MacroDataError
from bgilib.macro.client import ForexFactoryClient
from bgilib.macro.models import CalendarEvent
from indepth_analysis.skills.euro_macro.agents.forexfactory_agent import (
    ForexFactoryAgent,
)


@pytest.fixture
def patched_empty_fetch(monkeypatch):
    """Patch fetch_calendar to return an empty list."""

    def mock_fetch(self, period, *, force_refresh=False, countries=None, min_impact="Low"):
        return []

    monkeypatch.setattr(ForexFactoryClient, "fetch_calendar", mock_fetch)


def test_research_returns_agent_result(tmp_path, patched_empty_fetch):
    """ForexFactoryAgent.research returns AgentResult with extra populated."""
    agent = ForexFactoryAgent(db_path=tmp_path / "macro.db")
    result = asyncio.run(agent.research(2026, 5))

    assert result.agent_name == "ForexFactory"
    assert result.findings == []
    assert "events_by_period" in result.extra
    assert set(result.extra["events_by_period"].keys()) == {
        "lastweek",
        "thisweek",
        "nextweek",
    }
    assert result.extra["sigma_alerts"] == []
    assert result.error is None
    assert result.search_queries == ["lastweek", "thisweek", "nextweek"]
    assert result.extra["periods_failed"] == []
    assert result.extra["force_refresh"] is False
    assert "fetched_at_utc" in result.extra


def test_research_handles_fetch_error(tmp_path, monkeypatch):
    """ForexFactoryAgent.research handles MacroDataError without crashing."""

    def mock_fetch(self, period, *, force_refresh=False, countries=None, min_impact="Low"):
        raise MacroDataError("network failure")

    monkeypatch.setattr(ForexFactoryClient, "fetch_calendar", mock_fetch)

    agent = ForexFactoryAgent(db_path=tmp_path / "macro.db")
    result = asyncio.run(agent.research(2026, 5))

    assert result.agent_name == "ForexFactory"
    assert result.error is not None
    assert "network failure" in result.error
    # All three periods should have failed
    assert set(result.extra["periods_failed"]) == {
        "lastweek",
        "thisweek",
        "nextweek",
    }
    # Each period still gets an empty list entry
    assert result.extra["events_by_period"]["lastweek"] == []


def test_extra_is_json_serializable(tmp_path, patched_empty_fetch):
    """AgentResult.extra must survive JSON round-trip."""
    agent = ForexFactoryAgent(db_path=tmp_path / "macro.db")
    result = asyncio.run(agent.research(2026, 5))

    # Must not raise
    serialized = json.dumps(result.extra)
    restored = json.loads(serialized)
    assert restored["events_by_period"] == {
        "lastweek": [],
        "thisweek": [],
        "nextweek": [],
    }
    assert restored["sigma_alerts"] == []


def test_research_serializes_real_event(tmp_path, monkeypatch):
    """Real CalendarEvent objects are serialized via to_dict()."""

    sample_event = CalendarEvent(
        event_id="evt-1",
        country="EUR",
        title="German CPI m/m",
        impact="High",
        datetime_utc=datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
        forecast=0.3,
        previous=0.4,
        actual=None,
        is_released=False,
        source="json",
        raw_time="8:30am",
        raw_date="05-01-2026",
    )

    def mock_fetch(self, period, *, force_refresh=False, countries=None, min_impact="Low"):
        if period == "thisweek":
            return [sample_event]
        return []

    monkeypatch.setattr(ForexFactoryClient, "fetch_calendar", mock_fetch)

    agent = ForexFactoryAgent(db_path=tmp_path / "macro.db")
    result = asyncio.run(agent.research(2026, 5))

    # Round-trips through JSON cleanly
    serialized = json.dumps(result.extra)
    restored = json.loads(serialized)
    thisweek = restored["events_by_period"]["thisweek"]
    assert len(thisweek) == 1
    assert thisweek[0]["event_id"] == "evt-1"
    assert thisweek[0]["country"] == "EUR"
    assert thisweek[0]["impact"] == "High"
    assert thisweek[0]["datetime_utc"] == "2026-05-01T12:30:00+00:00"


def test_force_refresh_propagates(tmp_path, monkeypatch):
    """force_refresh=True is passed through to fetch_calendar."""

    captured: list[bool] = []

    def mock_fetch(self, period, *, force_refresh=False, countries=None, min_impact="Low"):
        captured.append(force_refresh)
        return []

    monkeypatch.setattr(ForexFactoryClient, "fetch_calendar", mock_fetch)

    agent = ForexFactoryAgent(db_path=tmp_path / "macro.db", force_refresh=True)
    result = asyncio.run(agent.research(2026, 5))

    assert all(captured)
    assert result.extra["force_refresh"] is True
