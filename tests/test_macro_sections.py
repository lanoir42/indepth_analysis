"""Tests for the deterministic ForexFactory macro section builder."""

from __future__ import annotations

from datetime import UTC, datetime

from indepth_analysis.models.euro_macro import AgentResult
from indepth_analysis.skills.euro_macro.macro_sections import (
    MacroSectionsBuilder,
    _format_value,
    _format_with_suffix,
    _infer_country_label,
    _recover_suffix,
    _to_kst_str,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
def _ev(
    title: str,
    country: str,
    impact: str,
    is_released: bool,
    *,
    actual: float | None = None,
    forecast: float | None = None,
    previous: float | None = None,
    dt_str: str = "2026-04-30T12:30:00+00:00",
    raw_time: str = "8:30am",
    actual_raw: str | None = None,
    forecast_raw: str | None = None,
) -> dict:
    """Build a single ForexFactory-style event dict."""
    surprise = (
        actual - forecast
        if (actual is not None and forecast is not None)
        else None
    )
    return {
        "event_id": f"{title[:8]}-{country}-{dt_str}",
        "title": title,
        "country": country,
        "impact": impact,
        "datetime_utc": dt_str,
        "is_released": is_released,
        "actual": actual,
        "forecast": forecast,
        "previous": previous,
        "source": "json",
        "raw_time": raw_time,
        "raw_date": "04-30-2026",
        "surprise": surprise,
        "actual_raw": actual_raw,
        "forecast_raw": forecast_raw,
        "previous_raw": None,
    }


def _make_ff_result(
    *,
    upcoming: list[dict] | None = None,
    released: list[dict] | None = None,
) -> AgentResult:
    """Build a synthetic AgentResult with events_by_period populated."""
    upcoming_events = upcoming if upcoming is not None else [
        _ev(
            "German CPI m/m",
            "EUR",
            "High",
            False,
            forecast=0.3,
            previous=0.2,
            dt_str="2026-05-02T12:30:00+00:00",
        ),
        _ev(
            "Good Friday",
            "EUR",
            "Holiday",
            False,
            dt_str="2026-05-02T00:00:00+00:00",
            raw_time="All Day",
        ),
        _ev(
            "UK GDP m/m",
            "GBP",
            "Medium",
            False,
            forecast=0.1,
            previous=0.0,
            dt_str="2026-05-05T08:00:00+00:00",
        ),
    ]
    released_events = released if released is not None else [
        _ev(
            "Core PCE Price Index m/m",
            "USD",
            "High",
            True,
            actual=0.3,
            forecast=0.2,
            dt_str="2026-04-25T12:30:00+00:00",
        ),
        _ev(
            "German Ifo Business Climate",
            "EUR",
            "High",
            True,
            actual=87.5,
            forecast=86.0,
            dt_str="2026-04-20T08:00:00+00:00",
        ),
        _ev(
            "Euro CPI Flash y/y",
            "EUR",
            "High",
            True,
            actual=2.7,
            forecast=2.5,
            dt_str="2026-04-15T09:00:00+00:00",
        ),
        _ev(
            "UK GDP m/m",
            "GBP",
            "Medium",
            True,
            actual=0.0,
            forecast=0.1,
            dt_str="2026-04-10T06:00:00+00:00",
        ),
    ]

    return AgentResult(
        agent_name="ForexFactory",
        findings=[],
        search_queries=["lastweek", "thisweek", "nextweek"],
        extra={
            "events_by_period": {
                "lastweek": released_events,
                "thisweek": upcoming_events + released_events,
                "nextweek": upcoming_events,
            },
            "fetched_at_utc": "2026-04-29T10:00:00+00:00",
            "periods_failed": [],
            "force_refresh": False,
            "sigma_alerts": [],
        },
    )


# ----------------------------------------------------------------------
# Format helpers
# ----------------------------------------------------------------------
class TestFormatHelpers:
    def test_to_kst_all_day(self) -> None:
        dt = datetime(2026, 5, 1, 4, 0, tzinfo=UTC)
        assert _to_kst_str(dt, "All Day") == "종일"

    def test_to_kst_tentative(self) -> None:
        dt = datetime(2026, 5, 1, 4, 0, tzinfo=UTC)
        assert _to_kst_str(dt, "Tentative") == "미정"

    def test_to_kst_empty(self) -> None:
        dt = datetime(2026, 5, 1, 4, 0, tzinfo=UTC)
        assert _to_kst_str(dt, "") == "시간미정"

    def test_to_kst_normal(self) -> None:
        # 12:30 UTC == 21:30 KST (KST = UTC+9)
        dt = datetime(2026, 4, 30, 12, 30, tzinfo=UTC)
        result = _to_kst_str(dt, "8:30am")
        assert "21:30" in result
        # April 30, 2026 is a Thursday
        assert "목" in result

    def test_infer_country_label_german(self) -> None:
        assert _infer_country_label("EUR", "German CPI m/m") == "독일"

    def test_infer_country_label_french(self) -> None:
        assert _infer_country_label("EUR", "French Industrial Output") == "프랑스"

    def test_infer_country_label_eur_fallback(self) -> None:
        assert _infer_country_label("EUR", "CPI Flash Estimate y/y") == "유로존"

    def test_infer_country_label_gbp(self) -> None:
        assert _infer_country_label("GBP", "GDP m/m") == "영국"

    def test_format_value_percent(self) -> None:
        assert _format_value(0.3, None, title="CPI") == "0.3%"

    def test_format_value_k_suffix(self) -> None:
        assert _format_value(220000.0, None, title="Jobless Claims") == "220K"

    def test_format_value_none(self) -> None:
        assert _format_value(None, None) == "–"

    def test_format_value_raw_suffix_priority(self) -> None:
        """Raw string suffix takes priority over title heuristic."""
        # raw="220K" -> suffix K, value 220000.0 -> "220K"
        result = _format_value(220000.0, "220K")
        assert result == "220K"

    def test_recover_suffix_from_raw(self) -> None:
        assert _recover_suffix("0.3%", "") == "%"
        assert _recover_suffix("220k", "") == "K"
        assert _recover_suffix("1.2M", "") == "M"

    def test_recover_suffix_from_title(self) -> None:
        assert _recover_suffix(None, "Core CPI Flash y/y") == "%"
        assert _recover_suffix(None, "Initial Jobless Claims") == "K"
        assert _recover_suffix(None, "German Ifo Business Climate") == ""

    def test_format_with_suffix_no_scientific(self) -> None:
        """Ensure :g scientific notation is not used for small values."""
        # 0.0001 with no suffix -> '0.000' (or similar), not '1e-04'
        assert "e" not in _format_with_suffix(0.0001, "").lower()


# ----------------------------------------------------------------------
# Section A — upcoming calendar
# ----------------------------------------------------------------------
class TestSectionA:
    def test_section_a_present(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        headings = [s.heading for s in sections]
        assert any("향후" in h or "캘린더" in h for h in headings)

    def test_section_a_excludes_holidays(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        a = next(s for s in sections if "캘린더" in s.heading)
        assert "Good Friday" not in a.content

    def test_section_a_korean_headers(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        a = next(s for s in sections if "캘린더" in s.heading)
        assert "일시 (KST)" in a.content
        assert "중요도" in a.content

    def test_section_a_no_usd_events(self) -> None:
        """USD events must be excluded from EUR-focused table."""
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        a = next(s for s in sections if "캘린더" in s.heading)
        assert "USD" not in a.content
        assert "PCE" not in a.content


# ----------------------------------------------------------------------
# Section B — released surprise table
# ----------------------------------------------------------------------
class TestSectionB:
    def test_section_b_present(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        headings = [s.heading for s in sections]
        assert any("서프라이즈" in h for h in headings)

    def test_section_b_shows_released_eur(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        b = next((s for s in sections if "서프라이즈" in s.heading), None)
        assert b is not None
        assert "Ifo" in b.content or "독일" in b.content

    def test_section_b_excludes_usd(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        b = next((s for s in sections if "서프라이즈" in s.heading), None)
        assert b is not None
        # USD Core PCE event must not appear
        assert "PCE" not in b.content

    def test_section_b_surprise_direction(self) -> None:
        """Up/down arrows reflect the sign of (actual - forecast)."""
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        b = next((s for s in sections if "서프라이즈" in s.heading), None)
        assert b is not None
        # Positive surprises (Ifo, Euro CPI) -> ▲; UK GDP miss -> ▼
        assert "▲" in b.content
        assert "▼" in b.content

    def test_section_b_empty_window(self) -> None:
        """When no released European events exist, render a placeholder."""
        ff = _make_ff_result(released=[])
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        b = next((s for s in sections if "서프라이즈" in s.heading), None)
        assert b is not None
        assert "발표된 주요 유럽 지표가 없습니다" in b.content

    def test_section_b_has_difference_column(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        b = next((s for s in sections if "서프라이즈" in s.heading), None)
        assert b is not None
        assert "차이" in b.content
        assert "실제치" in b.content


# ----------------------------------------------------------------------
# LLM digest
# ----------------------------------------------------------------------
class TestDigest:
    def test_digest_contains_forexfactory_attribution(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        digest = builder.build_llm_context_digest(ff)
        assert "ForexFactory" in digest

    def test_digest_non_empty(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        digest = builder.build_llm_context_digest(ff)
        assert len(digest) > 50

    def test_digest_includes_surprise_section(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        digest = builder.build_llm_context_digest(ff)
        assert "서프라이즈" in digest

    def test_digest_handles_none(self) -> None:
        builder = MacroSectionsBuilder(year=2026, month=5)
        assert builder.build_llm_context_digest(None) == ""


# ----------------------------------------------------------------------
# Builder edge cases
# ----------------------------------------------------------------------
class TestBuilderEdge:
    def test_build_returns_empty_for_none(self) -> None:
        builder = MacroSectionsBuilder(year=2026, month=5)
        assert builder.build(None) == []

    def test_build_orders_sections_a_then_b(self) -> None:
        ff = _make_ff_result()
        builder = MacroSectionsBuilder(year=2026, month=5)
        sections = builder.build(ff)
        assert len(sections) >= 2
        assert sections[0].heading.startswith("A.")
        assert sections[1].heading.startswith("B.")
