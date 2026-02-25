from __future__ import annotations

import logging
from datetime import UTC, datetime

from indepth_analysis.models.news import CalendarEvent, NewsArticle, NewsThumbnail

logger = logging.getLogger(__name__)


def parse_news(raw: list[dict], max_articles: int = 10) -> list[NewsArticle]:
    articles: list[NewsArticle] = []
    for item in raw[:max_articles]:
        try:
            thumbnail = _pick_thumbnail(item.get("thumbnail", {}))
            published = ""
            ts = item.get("providerPublishTime")
            if ts:
                published = datetime.fromtimestamp(ts, tz=UTC).strftime(
                    "%Y-%m-%d %H:%M UTC"
                )
            articles.append(
                NewsArticle(
                    title=item.get("title", ""),
                    publisher=item.get("publisher", ""),
                    link=item.get("link", ""),
                    published=published,
                    thumbnail=thumbnail,
                )
            )
        except Exception:
            logger.debug("Skipping malformed news item")
    return articles


def _pick_thumbnail(thumb_data: dict | None) -> NewsThumbnail | None:
    if not thumb_data:
        return None
    resolutions = thumb_data.get("resolutions", [])
    if not resolutions:
        return None
    best = max(resolutions, key=lambda r: r.get("width", 0) * r.get("height", 0))
    url = best.get("url", "")
    if not url:
        return None
    return NewsThumbnail(
        url=url,
        width=best.get("width", 0),
        height=best.get("height", 0),
    )


def parse_calendar(raw: dict) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    if not raw:
        return events

    # Earnings date
    earnings_date = raw.get("Earnings Date")
    if earnings_date:
        dates = earnings_date if isinstance(earnings_date, list) else [earnings_date]
        for d in dates:
            date_str = _format_date(d)
            if date_str:
                details_parts = []
                est_low = raw.get("Earnings Low")
                est_high = raw.get("Earnings High")
                est_avg = raw.get("Earnings Average")
                if est_avg is not None:
                    details_parts.append(f"EPS Est: {est_avg}")
                if est_low is not None and est_high is not None:
                    details_parts.append(f"Range: {est_low} - {est_high}")
                events.append(
                    CalendarEvent(
                        date=date_str,
                        event="Earnings",
                        details=", ".join(details_parts),
                    )
                )

    # Dividend date
    div_date = raw.get("Dividend Date")
    if div_date:
        date_str = _format_date(div_date)
        if date_str:
            events.append(
                CalendarEvent(
                    date=date_str,
                    event="Dividend",
                    details="",
                )
            )

    # Ex-dividend date
    ex_div_date = raw.get("Ex-Dividend Date")
    if ex_div_date:
        date_str = _format_date(ex_div_date)
        if date_str:
            events.append(
                CalendarEvent(
                    date=date_str,
                    event="Ex-Dividend",
                    details="",
                )
            )

    return events


def _format_date(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        return str(value)
    except Exception:
        return ""
