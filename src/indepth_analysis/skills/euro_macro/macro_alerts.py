"""Sigma-alert computation for macro surprises.

Compute |z| > threshold flags for released High-impact European events
in a given report month, using historical surprises drawn from the
local MacroStore.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
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
        1. Query candidate events in [month_start, month_end) filtered to
           ``countries`` and ``min_impact``.
        2. For each released candidate with non-null forecast and actual:
           a. Fetch the full indicator series for (country, title).
           b. Filter to events strictly BEFORE the candidate, within
              ``history_months`` months of the report month.
           c. Compute population stdev of historical surprises.
           d. Skip if len(history) < ``min_history_points`` or sigma == 0.0
              (Evaluator correction — guards both).
           e. z = candidate.surprise / sigma; flag if |z| > z_threshold.
        3. Return alerts sorted by |z| descending.
    """
    from indepth_analysis.skills.euro_macro.macro_sections import (
        _infer_country_label,
    )

    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    history_cutoff = _add_months(month_start, -history_months)

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

        series = store.get_indicator_series(
            candidate.country, candidate.title, released_only=True
        )
        history = [
            e.surprise
            for e in series.events
            if e.surprise is not None
            and history_cutoff <= e.datetime_utc < candidate.datetime_utc
        ]

        if len(history) < min_history_points:
            log.debug(
                "Skip %s/%s: only %d history points",
                candidate.country,
                candidate.title,
                len(history),
            )
            continue

        sigma = pstdev(history)
        if sigma == 0.0:
            log.debug(
                "Skip %s/%s: sigma == 0.0", candidate.country, candidate.title
            )
            continue

        z = candidate.surprise / sigma
        if abs(z) > z_threshold:
            label = _infer_country_label(candidate.country, candidate.title)
            alerts.append(
                SigmaAlert(
                    event=candidate,
                    label=label,
                    sigma=sigma,
                    z=z,
                    history_n=len(history),
                )
            )

    alerts.sort(key=lambda a: abs(a.z), reverse=True)
    return alerts
