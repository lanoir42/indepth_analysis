"""Historical backfill of Forex Factory calendar via HTML scraper."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from bgilib.errors import MacroDataError
from bgilib.macro.constants import ALL_TRACKED_COUNTRIES
from bgilib.macro.html_scraper import HTMLCalendarScraper
from bgilib.macro.storage import MacroStore

log = logging.getLogger("indepth_analysis.macro_backfill")

WAF_MARKERS = [
    "cf-browser-verification",
    "Just a moment...",
    "Attention Required! | Cloudflare",
    "cf_chl_opt",
    "__cf_chl",
    "CAPTCHA",
    "DDoS protection by Cloudflare",
]
MIN_VALID_HTML_LEN = 2000


@dataclass
class BackfillReport:
    """Summary of a backfill run."""

    weeks_requested: int
    weeks_succeeded: int = 0
    weeks_failed: list[date] = field(default_factory=list)
    events_written: int = 0
    waf_blocked: list[date] = field(default_factory=list)
    manual_confirmation_required: bool = False
    notes: list[str] = field(default_factory=list)


def detect_waf(html: str) -> str | None:
    """Return a marker string if WAF/Cloudflare blocking is detected, else None.

    Detection logic:
    - If response is short (< MIN_VALID_HTML_LEN) AND contains a WAF marker
      (case-insensitive): return that marker.
    - If response is short AND lacks 'calendar__table': return
      'short_response_missing_table'.
    - If any WAF marker appears verbatim in the response (any length): return it.
    - Otherwise: None.
    """
    if len(html) < MIN_VALID_HTML_LEN:
        for marker in WAF_MARKERS:
            if marker.lower() in html.lower():
                return marker
        if "calendar__table" not in html:
            return "short_response_missing_table"
    for marker in WAF_MARKERS:
        if marker in html:
            return marker
    return None


def backfill_history(
    *,
    weeks_back: int,
    db_path: Path = Path("data/macro_calendar.db"),
    countries: tuple[str, ...] = tuple(sorted(ALL_TRACKED_COUNTRIES)),
    min_impact: str = "Medium",
    rate_limit_seconds: float = 5.0,
    browser_cookie: str | None = None,
    progress: Callable[[int, int, date], None] | None = None,
) -> BackfillReport:
    """Scrape `weeks_back` weeks of Forex Factory HTML history.

    The window starts at the Monday `weeks_back - 1` weeks before the
    most recent Monday, and walks forward one week at a time.

    On a WAF/Cloudflare block, the run is aborted, the offending week is
    recorded under ``waf_blocked``, and ``manual_confirmation_required``
    is flipped to True so the caller can prompt the user to refresh
    their browser cookie.
    """
    report = BackfillReport(weeks_requested=weeks_back)
    store = MacroStore(db_path)

    today = date.today()
    days_since_monday = today.weekday()  # 0=Mon
    this_monday = today - timedelta(days=days_since_monday)
    start_monday = this_monday - timedelta(weeks=max(weeks_back - 1, 0))

    def _waf_fetcher(url: str) -> str:
        import httpx

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36"
            )
        }
        if browser_cookie:
            headers["Cookie"] = browser_cookie
        resp = httpx.get(url, headers=headers, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        body = resp.text
        reason = detect_waf(body)
        if reason:
            raise MacroDataError(f"WAF/blocked ({reason})")
        return body

    scraper = HTMLCalendarScraper(
        store,
        fetcher=_waf_fetcher,
        rate_limit_seconds=rate_limit_seconds,
    )

    for i in range(weeks_back):
        week = start_monday + timedelta(weeks=i)
        try:
            events = scraper.scrape_week(week)
            filtered = [e for e in events if e.country in countries]
            report.weeks_succeeded += 1
            report.events_written += len(filtered)
            log.info("Week %s: %d events (filtered=%d)", week, len(events), len(filtered))
        except MacroDataError as exc:
            err_str = str(exc)
            if "WAF" in err_str or "blocked" in err_str:
                report.waf_blocked.append(week)
                report.manual_confirmation_required = True
                report.notes.append(f"WAF block on {week}: {err_str}")
                log.warning("WAF block on %s — stopping backfill", week)
                break
            report.weeks_failed.append(week)
            report.notes.append(f"Error on {week}: {err_str}")
            log.warning("Error on %s: %s", week, exc)

        if progress:
            progress(i + 1, weeks_back, week)

    return report
