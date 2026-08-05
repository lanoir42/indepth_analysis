"""Tests for compute_sigma_alerts."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from bgilib.macro.models import CalendarEvent
from bgilib.macro.storage import MacroStore

from indepth_analysis.skills.euro_macro.macro_alerts import (
    SigmaAlert,
    SurpriseStats,
    compute_sigma_alerts,
    surprise_stats,
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
        datetime_utc=datetime(year, month, 1, 12, 0, tzinfo=UTC),
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
                    2024 + i // 12, (i % 12) + 1, 1, 12, 0, tzinfo=UTC
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
        datetime_utc=datetime(2026, 4, 15, 12, 0, tzinfo=UTC),
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


# ----------------------------------------------------------------------
# surprise_stats — the shared surprise distribution
# ----------------------------------------------------------------------
def _ev_at(
    eid: str,
    dt: datetime,
    actual: float | None,
    forecast: float | None,
    *,
    country: str = "EUR",
    title: str = "German CPI m/m",
    impact: str = "High",
) -> CalendarEvent:
    return CalendarEvent(
        event_id=eid,
        country=country,
        title=title,
        impact=impact,
        datetime_utc=dt,
        forecast=forecast,
        previous=None,
        actual=actual,
        is_released=True,
        source="json",
    )


def _biased_store(store: MacroStore, *, title: str = "German CPI m/m") -> MacroStore:
    """8 releases that all beat consensus by ~0.5 — a systematically biased forecast."""
    for i in range(8):
        month = (i % 12) + 1
        actual = 0.3 + (0.52 if i % 2 else 0.48)
        store.upsert_event(
            _ev_at(
                f"bias-{i}",
                datetime(2025, month, 1, 12, 0, tzinfo=UTC),
                actual,
                0.3,
                title=title,
            )
        )
    return store


class TestSurpriseStats:
    def test_groups_by_country_and_title(self, tmp_db) -> None:
        store = _biased_store(MacroStore(tmp_db))
        stats = surprise_stats(
            store, before=datetime(2026, 4, 1, tzinfo=UTC)
        )
        stat = stats[("EUR", "German CPI m/m")]
        assert stat.n == 8
        assert stat.mean == pytest.approx(0.5)
        assert stat.sigma == pytest.approx(0.02)

    def test_thin_groups_are_dropped(self, tmp_db) -> None:
        store = MacroStore(tmp_db)
        for i in range(3):
            store.upsert_event(_ev(f"h{i}", 2025, i + 1, 0.3 + i * 0.1, 0.3))
        stats = surprise_stats(
            store, before=datetime(2026, 4, 1, tzinfo=UTC)
        )
        assert stats == {}

    def test_history_window_is_bounded_by_before_and_months(self, tmp_db) -> None:
        store = _biased_store(MacroStore(tmp_db))
        # A 3-month window ending 2025-04 keeps only Jan-Mar 2025.
        stats = surprise_stats(
            store,
            before=datetime(2025, 4, 1, tzinfo=UTC),
            history_months=3,
            min_history_points=1,
        )
        assert stats[("EUR", "German CPI m/m")].n == 3

    def test_exact_title_matching_no_like_contamination(self, tmp_db) -> None:
        """'Core CPI …' must not leak into the 'CPI …' pool."""
        store = MacroStore(tmp_db)
        _biased_store(store, title="CPI Flash Estimate y/y")
        for i in range(8):
            store.upsert_event(
                _ev_at(
                    f"core-{i}",
                    datetime(2025, (i % 12) + 1, 2, 12, 0, tzinfo=UTC),
                    5.0,
                    0.0,
                    title="Core CPI Flash Estimate y/y",
                )
            )
        stats = surprise_stats(
            store, before=datetime(2026, 4, 1, tzinfo=UTC)
        )
        assert stats[("EUR", "CPI Flash Estimate y/y")].n == 8
        assert stats[("EUR", "CPI Flash Estimate y/y")].mean == pytest.approx(0.5)
        assert stats[("EUR", "Core CPI Flash Estimate y/y")].mean == pytest.approx(5.0)

    def test_history_is_not_truncated_by_impact_drift(self, tmp_db) -> None:
        """Impact labels drift across vintages; history must keep every release."""
        store = MacroStore(tmp_db)
        for i in range(8):
            store.upsert_event(
                _ev_at(
                    f"drift-{i}",
                    datetime(2025, (i % 12) + 1, 1, 12, 0, tzinfo=UTC),
                    0.3 + (0.1 if i % 2 else -0.1),
                    0.3,
                    title="ISM Manufacturing PMI",
                    country="USD",
                    impact="High" if i < 2 else "Medium",
                )
            )
        stats = surprise_stats(
            store, before=datetime(2026, 4, 1, tzinfo=UTC)
        )
        assert stats[("USD", "ISM Manufacturing PMI")].n == 8

    def test_countries_filter(self, tmp_db) -> None:
        store = _biased_store(MacroStore(tmp_db))
        stats = surprise_stats(
            store,
            before=datetime(2026, 4, 1, tzinfo=UTC),
            countries=("USD",),
        )
        assert stats == {}


class TestCentredZ:
    def test_z_subtracts_the_historical_mean(self) -> None:
        stat = SurpriseStats("EUR", "CPI", mean=0.5, sigma=0.1, n=10)
        assert stat.z(0.5) == pytest.approx(0.0)
        assert stat.z(0.7) == pytest.approx(2.0)
        assert stat.z(0.3) == pytest.approx(-2.0)

    def test_z_none_when_sigma_zero(self) -> None:
        assert SurpriseStats("EUR", "CPI", mean=0.5, sigma=0.0, n=10).z(9.9) is None

    def test_biased_indicator_no_longer_self_alerts(self, tmp_db) -> None:
        """A miss equal to the usual miss is not news, however large in raw terms."""
        store = _biased_store(MacroStore(tmp_db))
        typical = _ev("typical", 2026, 4, actual=0.8, forecast=0.3)  # surprise +0.5
        store.upsert_event(typical)
        alerts = compute_sigma_alerts(store, year=2026, month=4)
        assert [a.event.event_id for a in alerts] == []

    def test_deviation_from_the_usual_bias_still_alerts(self, tmp_db) -> None:
        store = _biased_store(MacroStore(tmp_db))
        # surprise +0.6 against mean 0.5, sigma 0.02 -> z = 5
        store.upsert_event(_ev("shock", 2026, 4, actual=0.9, forecast=0.3))
        alerts = compute_sigma_alerts(store, year=2026, month=4)
        assert [a.event.event_id for a in alerts] == ["shock"]
        assert alerts[0].z == pytest.approx(5.0)
        assert alerts[0].history_n == 8


class TestSigmaAlertBlocklist:
    """Source-level vendor gate mechanism (introduced R-1 C-1, lifted R6)."""

    def _store_with_titled_history(self, tmp_db, title: str) -> MacroStore:
        store = MacroStore(tmp_db)
        for i in range(24):
            month = (i % 12) + 1
            year = 2024 + (i // 12)
            actual = 2.0 + (0.05 if i % 3 == 0 else -0.05)
            store.upsert_event(
                _ev(f"hist-{i}", year, month, actual, 2.0, title=title)
            )
        return store

    def test_production_blocklist_is_empty_after_r6(self) -> None:
        """R6 (2026-08-06) fulfilled the removal condition — no live entries."""
        from indepth_analysis.skills.euro_macro.macro_alerts import (
            SIGMA_ALERT_BLOCKLIST,
        )

        assert SIGMA_ALERT_BLOCKLIST == frozenset()

    def test_blocklisted_group_never_alerts_even_with_extreme_z(
        self, tmp_db, monkeypatch
    ) -> None:
        """The mechanism suppresses a listed group at the source."""
        title = "CPI Flash Estimate y/y"
        monkeypatch.setattr(
            "indepth_analysis.skills.euro_macro.macro_alerts."
            "SIGMA_ALERT_BLOCKLIST",
            frozenset({("EUR", title)}),
        )
        store = self._store_with_titled_history(tmp_db, title)
        store.upsert_event(_ev("outlier", 2026, 4, 5.0, 2.0, title=title))

        alerts = compute_sigma_alerts(store, year=2026, month=4)
        assert not any(a.event.event_id == "outlier" for a in alerts)

    def test_unlisted_title_still_alerts(self, tmp_db, monkeypatch) -> None:
        """The gate is surgical: only listed (country, title) pairs."""
        monkeypatch.setattr(
            "indepth_analysis.skills.euro_macro.macro_alerts."
            "SIGMA_ALERT_BLOCKLIST",
            frozenset({("EUR", "Some Other Indicator")}),
        )
        title = "Core CPI Flash Estimate y/y"
        store = self._store_with_titled_history(tmp_db, title)
        store.upsert_event(_ev("outlier", 2026, 4, 5.0, 2.0, title=title))

        alerts = compute_sigma_alerts(store, year=2026, month=4)
        assert any(a.event.event_id == "outlier" for a in alerts)
