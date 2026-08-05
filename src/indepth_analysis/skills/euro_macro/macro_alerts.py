"""Sigma-alert computation for macro surprises.

Compute |z| > threshold flags for released High-impact European events
in a given report month, using historical surprises drawn from the
local MacroStore.

Two pieces live here:

* :func:`surprise_stats` — the reusable per-(country, title) surprise
  distribution (mean, sigma, n). Also consumed by Section B of the report
  to rank surprises in sigma units instead of raw magnitude.
* :func:`compute_sigma_alerts` — the Section C alert list, now a thin
  consumer of those statistics.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean, pstdev
from typing import TYPE_CHECKING

from bgilib.macro.constants import ALL_TRACKED_COUNTRIES

if TYPE_CHECKING:
    from bgilib.macro.storage import MacroStore

log = logging.getLogger("indepth_analysis.macro_alerts")

# Evaluator correction: min_history_points >= 6; guard sigma == 0.0
_DEFAULT_MIN_HISTORY = 6
_DEFAULT_Z_THRESHOLD = 2.0
_DEFAULT_HISTORY_MONTHS = 24


@dataclass(frozen=True)
class SurpriseStats:
    """Historical surprise distribution for one (country, title) pair."""

    country: str
    title: str
    mean: float
    sigma: float
    n: int

    def z(self, surprise: float) -> float | None:
        """Return the centred z-score of ``surprise``, or None if sigma == 0.

        Centring rationale (Advisor s-1)
        --------------------------------
        The score is ``(surprise - mean) / sigma``, not ``surprise / sigma``.

        Consensus forecasts for a given indicator are systematically biased:
        euro-area HICP forecasters have run persistently below the print for
        long stretches, so the *typical* surprise for that series is not
        zero. Dividing the raw surprise by sigma therefore measures distance
        from "no surprise" rather than distance from "the usual surprise",
        and every release of a biased indicator drifts toward the alert
        threshold in the same direction. Subtracting the historical mean
        removes that systematic component and leaves the genuinely
        unexpected part, which is what a review flag should react to.

        The cost is that a persistent bias is normalised away: an indicator
        that always beats by +0.2 stops alerting at +0.2. That is intended —
        a standing bias belongs in the narrative, not in a surprise alert.
        """
        if self.sigma == 0.0:
            return None
        return (surprise - self.mean) / self.sigma

    def to_dict(self) -> dict[str, float | str | int]:
        return {
            "country": self.country,
            "title": self.title,
            "mean": self.mean,
            "sigma": self.sigma,
            "n": self.n,
        }


@dataclass(frozen=True)
class SigmaAlert:
    """A single statistically-significant macro surprise."""

    event: object  # CalendarEvent (avoid circular import at class level)
    label: str  # Korean country/region label e.g. "독일"
    sigma: float
    z: float
    history_n: int


def _add_months(dt: datetime, months: int) -> datetime:
    """Return ``dt`` shifted by ``months`` months (clamped to month-end if needed)."""
    total = dt.year * 12 + (dt.month - 1) + months
    year, month_idx = divmod(total, 12)
    return dt.replace(year=year, month=month_idx + 1)


def surprise_stats(
    store: MacroStore,
    *,
    before: datetime | None = None,
    countries: tuple[str, ...] = tuple(sorted(ALL_TRACKED_COUNTRIES)),
    min_impact: str | None = None,
    history_months: int = _DEFAULT_HISTORY_MONTHS,
    min_history_points: int = _DEFAULT_MIN_HISTORY,
) -> dict[tuple[str, str], SurpriseStats]:
    """Return the surprise distribution per (country, title) pair.

    History window is ``[before - history_months, before)``, i.e. the
    reference distribution is fixed before the period under review so every
    event in that period is scored against the same yardstick (no
    within-period look-ahead, and no dependence on release ordering).

    Args:
        store: Macro store to read released events from.
        before: Exclusive upper bound of the history window. Defaults to now.
        countries: Country codes to include.
        min_impact: Optional impact floor for the *history* pool. Defaults to
            ``None`` — no filter. Impact labels drift across vintages of the
            same indicator (ForexFactory has carried
            ``ISM Manufacturing PMI`` as both High and Medium), so filtering
            history by impact silently truncates the sample. Filter
            candidates by impact instead, at the call site.
        history_months: Length of the history window in months.
        min_history_points: Groups with fewer observations are dropped.

    Returns:
        ``{(country, title): SurpriseStats}``. Titles are matched exactly —
        pairs are formed from the stored rows themselves, so no ``LIKE``
        contamination is possible (``Core CPI Flash Estimate y/y`` never
        lands in the ``CPI Flash Estimate y/y`` pool).
    """
    if before is None:
        before = datetime.now(UTC)
    since = _add_months(before, -history_months)

    events = store.query_events(since=since, until=before, min_impact=min_impact)

    buckets: dict[tuple[str, str], list[float]] = {}
    for event in events:
        if event.country not in countries:
            continue
        if not event.is_released:
            continue
        surprise = event.surprise
        if surprise is None:
            continue
        buckets.setdefault((event.country, event.title), []).append(surprise)

    stats: dict[tuple[str, str], SurpriseStats] = {}
    for (country, title), values in buckets.items():
        if len(values) < min_history_points:
            log.debug(
                "Skip %s/%s: only %d history points", country, title, len(values)
            )
            continue
        stats[(country, title)] = SurpriseStats(
            country=country,
            title=title,
            mean=fmean(values),
            sigma=pstdev(values),
            n=len(values),
        )
    return stats


def compute_sigma_alerts(
    store: MacroStore,
    *,
    year: int,
    month: int,
    countries: tuple[str, ...] = tuple(sorted(ALL_TRACKED_COUNTRIES)),
    min_impact: str = "High",
    z_threshold: float = _DEFAULT_Z_THRESHOLD,
    history_months: int = _DEFAULT_HISTORY_MONTHS,
    min_history_points: int = _DEFAULT_MIN_HISTORY,
) -> list[SigmaAlert]:
    """Find released High-impact surprises in (year, month) where |z| > z_threshold.

    Algorithm:
        1. Build the reference distribution with :func:`surprise_stats` over
           the ``history_months`` window ending at the first day of the
           report month.
        2. Query candidate events in [month_start, month_end) filtered to
           ``countries`` and ``min_impact``.
        3. For each released candidate with a non-null surprise, score it
           against the stats for its exact (country, title) pair:
           ``z = (surprise - mean) / sigma``. Skip when no stats exist
           (fewer than ``min_history_points`` observations) or sigma == 0.0
           (Evaluator correction — guards both).
        4. Flag when ``|z| > z_threshold``; return sorted by |z| descending.
    """
    from indepth_analysis.skills.euro_macro.macro_sections import (
        _infer_country_label,
    )

    month_start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=UTC)

    stats = surprise_stats(
        store,
        before=month_start,
        countries=countries,
        history_months=history_months,
        min_history_points=min_history_points,
    )

    candidates = store.query_events(
        since=month_start,
        until=month_end,
        min_impact=min_impact,
    )
    candidates = [
        e
        for e in candidates
        if e.country in countries
        and e.is_released
        and e.forecast is not None
        and e.actual is not None
    ]

    alerts: list[SigmaAlert] = []
    for candidate in candidates:
        if candidate.surprise is None:
            continue

        stat = stats.get((candidate.country, candidate.title))
        if stat is None:
            continue

        z = stat.z(candidate.surprise)
        if z is None:
            log.debug("Skip %s/%s: sigma == 0.0", candidate.country, candidate.title)
            continue

        if abs(z) > z_threshold:
            label = _infer_country_label(candidate.country, candidate.title)
            alerts.append(
                SigmaAlert(
                    event=candidate,
                    label=label,
                    sigma=stat.sigma,
                    z=z,
                    history_n=stat.n,
                )
            )

    alerts.sort(key=lambda a: abs(a.z), reverse=True)
    return alerts
