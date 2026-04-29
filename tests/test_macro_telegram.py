"""Tests for macro_telegram idempotency and send behavior."""
from __future__ import annotations

from datetime import datetime, timezone

from bgilib.macro.models import CalendarEvent
from bgilib.macro.storage import MacroStore
from indepth_analysis.skills.euro_macro.macro_alerts import SigmaAlert
from indepth_analysis.skills.euro_macro.macro_telegram import send_sigma_alerts


def _make_alert(event_id: str = "ev-test-001") -> SigmaAlert:
    ev = CalendarEvent(
        event_id=event_id,
        country="EUR",
        title="German CPI m/m",
        impact="High",
        datetime_utc=datetime(2026, 4, 30, 12, 30, tzinfo=timezone.utc),
        forecast=0.2,
        previous=None,
        actual=0.5,
        is_released=True,
        source="json",
        raw_time="8:30am",
        raw_date="04-30-2026",
    )
    return SigmaAlert(event=ev, label="독일", sigma=0.05, z=6.0, history_n=24)


def test_no_token_returns_zero(tmp_db, monkeypatch) -> None:
    """Without env vars, send_sigma_alerts returns 0."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID_MACRO", raising=False)
    store = MacroStore(tmp_db)
    assert send_sigma_alerts([], store=store) == 0


def test_idempotent_no_double_send(tmp_db, monkeypatch) -> None:
    """Second call for same event does not send again."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_MACRO", "12345")

    send_count = 0

    class FakeBot:
        def send_message(self, chat_id, text, **kwargs):
            nonlocal send_count
            send_count += 1
            return True

    store = MacroStore(tmp_db)
    alert = _make_alert()

    bot = FakeBot()
    n1 = send_sigma_alerts([alert], store=store, bot=bot, chat_id="12345")
    n2 = send_sigma_alerts([alert], store=store, bot=bot, chat_id="12345")

    assert n1 == 1
    assert n2 == 0  # idempotent — already recorded
    assert send_count == 1


def test_failed_send_not_recorded(tmp_db, monkeypatch) -> None:
    """If bot.send_message returns False, alert is NOT recorded as sent."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_MACRO", "12345")

    class FailingBot:
        def send_message(self, *args, **kwargs):
            return False

    store = MacroStore(tmp_db)
    alert = _make_alert("ev-fail-001")
    bot = FailingBot()

    n = send_sigma_alerts([alert], store=store, bot=bot, chat_id="12345")
    assert n == 0
    # Critical: failed sends must remain unmarked so they can be retried.
    assert not store.alert_already_sent("ev-fail-001", "sigma_alert", "12345")


def test_multiple_alerts_partial_failure(tmp_db, monkeypatch) -> None:
    """Mixed pass/fail: only successful ones are recorded."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID_MACRO", "ch")

    class FlakyBot:
        def __init__(self):
            self.calls = 0

        def send_message(self, *args, **kwargs):
            self.calls += 1
            return self.calls % 2 == 1  # 1st: True, 2nd: False, 3rd: True

    store = MacroStore(tmp_db)
    alerts = [_make_alert(f"id-{i}") for i in range(3)]
    bot = FlakyBot()

    n = send_sigma_alerts(alerts, store=store, bot=bot, chat_id="ch")
    assert n == 2
    assert store.alert_already_sent("id-0", "sigma_alert", "ch")
    assert not store.alert_already_sent("id-1", "sigma_alert", "ch")
    assert store.alert_already_sent("id-2", "sigma_alert", "ch")
