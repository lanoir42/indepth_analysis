"""Tests for compute_sigma_alerts."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bgilib.macro.models import CalendarEvent
from bgilib.macro.storage import MacroStore
from indepth_analysis.skills.euro_macro.macro_alerts import (
    SigmaAlert,
    compute_sigma_alerts,
)


def _ev(
    eid: str,
    year: int,
    month: int,
    actual: float | None,
    forecast: float | None,
    *,
    country: str = "EUR",
    title: str = "German CPI m/m",
    is_released: bool = True,
) -> CalendarEvent:
    return CalendarEvent(
        event_id=eid,
        country=country,
        title=title,
        impact="High",
        datetime_utc=datetime(year, month, 1, 12, 0, tzinfo=timezone.utc),
        forecast=forecast,
        previous=None,
        actual=actual,
        is_released=is_released,
        source="json",
        raw_time="8:30am",
        raw_date=f"{month:02d}-01-{year}",
    )


@pytest.fixture
def store_with_history(tmp_db) -> MacroStore:
    store = MacroStore(tmp_db)
    # 24 months of history: surprises clustering with small variance.
    for i in range(24):
        month = (i % 12) + 1
        year = 2024 + (i // 12)
        actual = 0.3 + (0.05 if i % 3 == 0 else -0.05)
        forecast = 0.3
        store.upsert_event(_ev(f"hist-{i}", year, month, actual, forecast))
    return store


def test_high_z_flagged(store_with_history: MacroStore) -> None:
    """Event with |z| > 2.0 is flagged."""
    outlier = _ev("outlier", 2026, 4, actual=0.8, forecast=0.3)
    store_with_history.upsert_event(outlier)

    alerts = compute_sigma_alerts(store_with_history, year=2026, month=4)
    assert any(a.event.event_id == "outlier" for a in alerts)


def test_low_z_not_flagged(store_with_history: MacroStore) -> None:
    """Event with |z| < 2.0 is not flagged."""
    normal = _ev("normal", 2026, 4, actual=0.32, forecast=0.3)
    store_with_history.upsert_event(normal)

    alerts = compute_sigma_alerts(store_with_history, year=2026, month=4)
    assert not any(a.event.event_id == "normal" for a in alerts)


def test_sigma_zero_skipped(tmp_db) -> None:
    """Events with all-identical historical surprises (σ=0) are skipped."""
    store = MacroStore(tmp_db)
    for i in range(10):
        store.upsert_event(_ev(f"h{i}", 2024 + i // 12, (i % 12) + 1, 0.3, 0.3))
    candidate = _ev("cand", 2026, 4, actual=0.8, forecast=0.3)
    store.upsert_event(candidate)

    alerts = compute_sigma_alerts(store, year=2026, month=4)
    assert not any(a.event.event_id == "cand" for a in alerts)


def test_insufficient_history_skipped(tmp_db) -> None:
    """Skip if fewer than min_history_points."""
    store = MacroStore(tmp_db)
    for i in range(3):  # only 3 points; default min is 6
        store.upsert_event(
            _ev(f"h{i}", 2025, i + 1, 0.3 + i * 0.1, 0.3)
        )
    candidate = _ev("cand", 2026, 4, actual=1.0, forecast=0.3)
    store.upsert_event(candidate)

    alerts = compute_sigma_alerts(store, year=2026, month=4)
    assert len(alerts) == 0


def test_alerts_sorted_by_z_desc(store_with_history: MacroStore) -> None:
    """Alerts are sorted by |z| descending."""
    big_eur = _ev("big", 2026, 4, actual=1.0, forecast=0.3)
    store_with_history.upsert_event(big_eur)

    # Add GBP / GDP history then a moderate-surprise candidate
    for i in range(8):
        store_with_history.upsert_event(
            CalendarEvent(
                event_id=f"gbp-h{i}",
                country="GBP",
                title="GDP m/m",
                impact="High",
                datetime_utc=datetime(
                    2024 + i // 12, (i % 12) + 1, 1, 12, 0, tzinfo=timezone.utc
                ),
                forecast=0.1,
                previous=None,
                actual=0.1 + (0.02 if i % 2 else -0.02),
                is_released=True,
                source="json",
                raw_time="8:30am",
                raw_date="01-01-2024",
            )
        )
    small_gbp = CalendarEvent(
        event_id="small",
        country="GBP",
        title="GDP m/m",
        impact="High",
        datetime_utc=datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc),
        forecast=0.1,
        previous=None,
        actual=0.5,
        is_released=True,
        source="json",
        raw_time="8:30am",
        raw_date="04-15-2026",
    )
    store_with_history.upsert_event(small_gbp)

    alerts = compute_sigma_alerts(store_with_history, year=2026, month=4)
    if len(alerts) >= 2:
        assert abs(alerts[0].z) >= abs(alerts[1].z)


def test_sigma_alert_dataclass_frozen() -> None:
    """SigmaAlert is a frozen dataclass."""
    ev = _ev("e", 2026, 4, 0.5, 0.3)
    a = SigmaAlert(event=ev, label="독일", sigma=0.05, z=4.0, history_n=12)
    assert a.label == "독일"
    with pytest.raises(Exception):
        a.label = "프랑스"  # type: ignore[misc]
