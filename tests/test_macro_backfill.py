"""Tests for macro_backfill: detect_waf and backfill_history."""
from __future__ import annotations

import pytest

from indepth_analysis.skills.euro_macro.macro_backfill import (
    BackfillReport,
    backfill_history,
    detect_waf,
)

CLOUDFLARE_HTML = """
<html><head><title>Just a moment...</title></head>
<body>
<div>Just a moment...</div>
<script>cf_chl_opt = {}</script>
</body></html>
"""

VALID_HTML = """
<html><body>
<table class="calendar__table">
  <tr class="calendar__row--day-breaker"><td class="calendar__date">Mon Apr 28</td></tr>
  <tr class="calendar__row">
    <td class="calendar__currency">EUR</td>
    <td class="calendar__impact"><span class="icon icon--ff-impact-red"></span></td>
    <td class="calendar__time">8:30am</td>
    <td class="calendar__event"><span class="calendar__event-title">German CPI m/m</span></td>
    <td class="calendar__actual">0.3%</td>
    <td class="calendar__forecast">0.2%</td>
    <td class="calendar__previous">0.4%</td>
  </tr>
</table>
</body></html>
"""


def test_detect_waf_cloudflare():
    assert detect_waf(CLOUDFLARE_HTML) is not None


def test_detect_waf_valid_html():
    assert detect_waf(VALID_HTML) is None


def test_detect_waf_short_html():
    assert detect_waf("<html><body>short</body></html>") is not None


def test_detect_waf_missing_table():
    """Long HTML with no WAF marker and no calendar__table is not flagged."""
    long_html = "<html><body>" + "x" * 3000 + "</body></html>"
    result = detect_waf(long_html)
    assert result is None  # Not a WAF block — just an empty valid page


def test_backfill_history_success(tmp_path, monkeypatch):
    """Successful scrape writes events and returns correct counts."""
    import httpx

    class FakeResponse:
        text = VALID_HTML
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResponse())

    report = backfill_history(
        weeks_back=2, db_path=tmp_path / "macro.db", rate_limit_seconds=0
    )
    assert report.weeks_succeeded == 2
    assert report.events_written >= 0
    assert report.waf_blocked == []
    assert not report.manual_confirmation_required


def test_backfill_history_waf_block(tmp_path, monkeypatch):
    """WAF response sets manual_confirmation_required and stops."""
    import httpx

    class FakeWAFResponse:
        text = CLOUDFLARE_HTML
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeWAFResponse())

    report = backfill_history(
        weeks_back=4, db_path=tmp_path / "macro.db", rate_limit_seconds=0
    )
    assert report.manual_confirmation_required is True
    assert len(report.waf_blocked) >= 1
    assert report.weeks_succeeded < 4  # Did not complete all weeks


def test_backfill_report_dataclass():
    r = BackfillReport(weeks_requested=5)
    assert r.weeks_succeeded == 0
    assert r.manual_confirmation_required is False
    assert r.waf_blocked == []


def test_backfill_history_progress_callback(tmp_path, monkeypatch):
    """Progress callback invoked once per successful week."""
    import httpx

    class FakeResponse:
        text = VALID_HTML
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "get", lambda *a, **kw: FakeResponse())

    calls: list[tuple[int, int]] = []

    def cb(i, total, week):
        calls.append((i, total))

    backfill_history(
        weeks_back=3,
        db_path=tmp_path / "macro.db",
        rate_limit_seconds=0,
        progress=cb,
    )
    assert len(calls) == 3
    assert calls[0] == (1, 3)
    assert calls[-1] == (3, 3)
