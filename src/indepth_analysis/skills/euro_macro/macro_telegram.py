"""Telegram alerting for macro surprises.

Sends Korean-language sigma-alert notifications via the bgilib Telegram
bot wrapper. Idempotent across runs — successful sends are recorded in
the ``alerts_sent`` table so repeats are suppressed.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bgilib.macro.storage import MacroStore

    from indepth_analysis.skills.euro_macro.macro_alerts import SigmaAlert

log = logging.getLogger("indepth_analysis.macro_telegram")

_KIND_SIGMA = "sigma_alert"


def _format_alert_text(
    *,
    label: str,
    title: str,
    actual_fmt: str,
    forecast_fmt: str,
    z: float,
    history_n: int,
    kst_str: str,
    impact: str,
) -> str:
    direction = "▲" if z > 0 else "▼"
    return (
        f"<b>[FF 매크로 알림 · 이상 서프라이즈]</b>\n"
        f"{label} · {title}\n"
        f"실제 {actual_fmt} vs 예상 {forecast_fmt}\n"
        f"편차 {direction} {abs(z):.1f}σ (n={history_n})\n"
        f"발표 {kst_str} · 중요도 {impact}"
    )


def send_sigma_alerts(
    alerts: list[SigmaAlert],
    *,
    store: MacroStore,
    bot: Any | None = None,
    chat_id: str | None = None,
) -> int:
    """Send Telegram messages for sigma alerts. Returns count of NEW sends.

    Reads env vars ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID_MACRO``
    when ``bot`` and ``chat_id`` are not supplied. If no token / chat is
    configured, the function logs and returns 0 (graceful no-op).

    Idempotency:
        Each alert is keyed on (event_id, "sigma_alert", chat_id) in the
        ``alerts_sent`` table. The row is written ONLY after a successful
        send (Evaluator correction) — failed sends will be retried on the
        next run.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID_MACRO")

    if not token or not chat_id:
        log.info(
            "Telegram disabled — TELEGRAM_BOT_TOKEN or "
            "TELEGRAM_CHAT_ID_MACRO not set"
        )
        return 0

    if bot is None:
        from bgilib.telegram.bot import TelegramBot

        bot = TelegramBot(token=token)

    from indepth_analysis.skills.euro_macro.macro_sections import (
        _format_value,
        _to_kst_str,
    )

    sent = 0
    for alert in alerts:
        event = alert.event
        eid = event.event_id

        if store.alert_already_sent(eid, _KIND_SIGMA, chat_id):
            log.debug("Alert already sent for %s", eid)
            continue

        kst_str = _to_kst_str(event.datetime_utc, event.raw_time)
        actual_fmt = _format_value(event.actual, None, title=event.title)
        forecast_fmt = _format_value(event.forecast, None, title=event.title)

        text = _format_alert_text(
            label=alert.label,
            title=event.title,
            actual_fmt=actual_fmt,
            forecast_fmt=forecast_fmt,
            z=alert.z,
            history_n=alert.history_n,
            kst_str=kst_str,
            impact=event.impact,
        )

        ok = bot.send_message(chat_id, text, parse_mode="HTML")
        if ok:
            store.record_alert_sent(eid, _KIND_SIGMA, chat_id)
            sent += 1
        else:
            log.warning("Failed to send Telegram alert for %s", eid)

    return sent


def _send_sigma_alerts_from_dicts(
    alerts_data: list[dict],
    *,
    store: MacroStore,
    bot: Any | None = None,
    chat_id: str | None = None,
) -> int:
    """Send sigma alerts where each alert is a serialized dict.

    Internal helper used by the orchestrator when crossing the
    JSON-serialization boundary (``ff_result.extra["sigma_alerts"]``).

    The dict shape mirrors what ForexFactoryAgent stashes:
        {
            "event": <CalendarEvent.to_dict() output>,
            "label": <str>,
            "sigma": <float>,
            "z": <float>,
            "history_n": <int>,
        }
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID_MACRO")

    if not token or not chat_id:
        log.info(
            "Telegram disabled — TELEGRAM_BOT_TOKEN or "
            "TELEGRAM_CHAT_ID_MACRO not set"
        )
        return 0

    if bot is None:
        from bgilib.telegram.bot import TelegramBot

        bot = TelegramBot(token=token)

    from indepth_analysis.skills.euro_macro.macro_sections import (
        _format_value,
        _to_kst_str,
    )

    sent = 0
    for alert in alerts_data:
        event = alert.get("event") or {}
        eid = event.get("event_id")
        if not eid:
            continue

        if store.alert_already_sent(eid, _KIND_SIGMA, chat_id):
            log.debug("Alert already sent for %s", eid)
            continue

        try:
            dt_utc = datetime.fromisoformat(event["datetime_utc"])
        except (KeyError, TypeError, ValueError):
            log.warning("Skipping alert with invalid datetime_utc: %s", eid)
            continue

        title = event.get("title", "")
        kst_str = _to_kst_str(dt_utc, event.get("raw_time"))
        actual_fmt = _format_value(event.get("actual"), None, title=title)
        forecast_fmt = _format_value(event.get("forecast"), None, title=title)

        text = _format_alert_text(
            label=alert.get("label", ""),
            title=title,
            actual_fmt=actual_fmt,
            forecast_fmt=forecast_fmt,
            z=float(alert.get("z", 0.0)),
            history_n=int(alert.get("history_n", 0)),
            kst_str=kst_str,
            impact=event.get("impact", ""),
        )

        ok = bot.send_message(chat_id, text, parse_mode="HTML")
        if ok:
            store.record_alert_sent(eid, _KIND_SIGMA, chat_id)
            sent += 1
        else:
            log.warning("Failed to send Telegram alert for %s", eid)

    return sent
