"""ForexFactory agent — fetches macro calendar data via bgilib.macro."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bgilib.errors import MacroDataError
from bgilib.macro.client import ForexFactoryClient

from indepth_analysis.models.euro_macro import AgentResult

logger = logging.getLogger(__name__)

_PERIODS: tuple[str, ...] = ("lastweek", "thisweek", "nextweek")


class ForexFactoryAgent:
    """Always-on agent that pulls Forex Factory weekly JSON feeds.

    The agent does not produce free-form ResearchFindings. Instead it stores
    structured calendar data in ``AgentResult.extra`` so deterministic report
    sections can be assembled post-synthesis.
    """

    name = "ForexFactory"

    def __init__(
        self,
        *,
        db_path: Path = Path("data/macro_calendar.db"),
        force_refresh: bool = False,
        countries: tuple[str, ...] = ("EUR", "GBP", "CHF", "SEK"),
    ) -> None:
        self._db_path = db_path
        self._force_refresh = force_refresh
        self._countries = countries
        self._client: ForexFactoryClient | None = None

    def _ensure_client(self) -> ForexFactoryClient:
        if self._client is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._client = ForexFactoryClient(db_path=self._db_path)
        return self._client

    async def research(self, year: int, month: int) -> AgentResult:
        """Fetch lastweek/thisweek/nextweek calendars and return AgentResult."""
        client = self._ensure_client()

        events_by_period: dict[str, list[dict]] = {}
        periods_failed: list[str] = []
        errors: list[str] = []

        for period in _PERIODS:
            try:
                events = await asyncio.to_thread(
                    client.fetch_calendar,
                    period,
                    force_refresh=self._force_refresh,
                    countries=list(self._countries),
                    min_impact="Low",
                )
                events_by_period[period] = [e.to_dict() for e in events]
            except MacroDataError as exc:
                logger.warning(
                    "ForexFactoryAgent: %s fetch failed: %s", period, exc
                )
                events_by_period[period] = []
                periods_failed.append(period)
                errors.append(f"{period}: {exc}")
            except Exception as exc:
                logger.exception(
                    "ForexFactoryAgent: unexpected error fetching %s", period
                )
                events_by_period[period] = []
                periods_failed.append(period)
                errors.append(f"{period}: {exc}")

        # Query DB for released European events in the 30-day lookback window
        # (JSON "lastweek" endpoint returns 404, so DB is the authoritative source).
        released_events_db: list[dict] = []
        try:
            anchor_start = datetime(year, month, 1, tzinfo=UTC)
            window_start = anchor_start - timedelta(days=30)
            window_end = anchor_start + timedelta(days=7)
            for country in self._countries:
                db_events = client.store.query_events(
                    country=country,
                    since=window_start,
                    until=window_end,
                    min_impact="Medium",
                )
                released_events_db.extend(
                    e.to_dict() for e in db_events if e.is_released
                )
        except Exception as exc:
            logger.warning("DB released-events query failed: %s", exc)

        # Compute sigma alerts from the now-populated MacroStore (M4).
        sigma_alerts_raw: list[dict] = []
        try:
            from indepth_analysis.skills.euro_macro.macro_alerts import (
                compute_sigma_alerts,
            )

            alerts = await asyncio.to_thread(
                compute_sigma_alerts,
                client.store,
                year=year,
                month=month,
            )
            sigma_alerts_raw = [
                {
                    "event": a.event.to_dict(),
                    "label": a.label,
                    "sigma": a.sigma,
                    "z": a.z,
                    "history_n": a.history_n,
                }
                for a in alerts
            ]
        except Exception as exc:
            logger.warning("Sigma alert computation failed: %s", exc)
            sigma_alerts_raw = []

        extra: dict = {
            "events_by_period": events_by_period,
            "released_events_db": released_events_db,
            "fetched_at_utc": datetime.now(UTC).isoformat(),
            "periods_failed": periods_failed,
            "force_refresh": self._force_refresh,
            "sigma_alerts": sigma_alerts_raw,
        }

        return AgentResult(
            agent_name=self.name,
            findings=[],
            search_queries=list(_PERIODS),
            error="; ".join(errors) if errors else None,
            extra=extra,
        )
