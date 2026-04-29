"""Deterministic post-synthesis builder for ForexFactory macro sections.

Section A: upcoming 14-day calendar table.
Section B: 30-day surprise table (M2).
Section C: stub (M4).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from indepth_analysis.models.euro_macro import AgentResult, ReportSection

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
KOR_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
EXCLUDED_IMPACTS = frozenset({"Holiday"})
EURO_COUNTRY_LABELS = {
    "EUR": "유로존",
    "GBP": "영국",
    "CHF": "스위스",
    "SEK": "스웨덴",
    "NOK": "노르웨이",
    "DKK": "덴마크",
}
TITLE_COUNTRY_PREFIXES = {
    "German": "독일",
    "French": "프랑스",
    "Italian": "이탈리아",
    "Spanish": "스페인",
    "Dutch": "네덜란드",
    "Greek": "그리스",
    "Euro": "유로존",
}
SPECIAL_RAW_TIMES = {
    "all day": "종일",
    "tentative": "미정",
    "": "시간미정",
}
IMPACT_LABELS_KOR = {"High": "높음", "Medium": "중간", "Low": "낮음"}
ALLOWED_IMPACTS = frozenset({"Medium", "High"})
EUROPE_FOCUS_COUNTRIES = frozenset({"EUR", "GBP", "CHF", "SEK"})
MAX_ROWS = 30
WINDOW_DAYS = 14
SECTION_B_LOOKBACK_DAYS = 30
SECTION_B_LOOKAHEAD_DAYS = 7
SECTION_B_MAX_ROWS = 15
DIGEST_SURPRISE_TOP_N = 8

# Heuristic mapping: indicator title keyword -> unit suffix.
# Used when the raw forecast/previous/actual string is unavailable
# (events_by_period dicts strip the original suffix during numeric parsing).
_TITLE_UNIT_HINTS: dict[str, str] = {
    # percent-based indicators
    "CPI": "%",
    "PCE": "%",
    "PPI": "%",
    "HICP": "%",
    "Inflation": "%",
    "Unemployment": "%",
    "GDP": "%",
    "Interest Rate": "%",
    "Deposit Rate": "%",
    "Bank Rate": "%",
    "Cash Rate": "%",
    "Wage": "%",
    "Earnings": "%",
    "Retail Sales": "%",
    # count-based (thousands)
    "Jobless Claims": "K",
    "NFP": "K",
    "Nonfarm": "K",
    "Employment Change": "K",
    # Indices / no suffix
    "PMI": "",
    "Ifo": "",
    "ZEW": "",
    "Sentiment": "",
    "Confidence": "",
}


# ----------------------------------------------------------------------
# Module-level helpers (also exposed for unit tests)
# ----------------------------------------------------------------------
def _to_kst_str(dt_utc: datetime, raw_time: str | None) -> str:
    """Render a UTC datetime as a KST 'MM-DD (요일) HH:MM' string.

    Special raw_time values ('All Day', 'Tentative', '') are mapped to
    Korean placeholders.
    """
    if raw_time is not None:
        key = raw_time.strip().lower()
        if key in SPECIAL_RAW_TIMES:
            return SPECIAL_RAW_TIMES[key]
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC)
    d = dt_utc.astimezone(KST)
    return (
        f"{d.month:02d}-{d.day:02d} "
        f"({KOR_WEEKDAYS[d.weekday()]}) "
        f"{d.hour:02d}:{d.minute:02d}"
    )


def _infer_country_label(country: str, title: str) -> str:
    """Return a Korean country/region label, preferring title-based hints."""
    if title:
        for prefix, label in TITLE_COUNTRY_PREFIXES.items():
            if title.startswith(prefix):
                return label
    return EURO_COUNTRY_LABELS.get(country, country)


def _recover_suffix(raw: str | None, title: str) -> str:
    """Recover a numeric suffix (K/M/B/%) from a raw string or a title hint."""
    if raw:
        m = re.search(r"([KMBkmb%])\s*$", str(raw).strip())
        if m:
            ch = m.group(1)
            return ch.upper() if ch.lower() in ("k", "m", "b") else ch
    if title:
        title_lower = title.lower()
        for keyword, hint in _TITLE_UNIT_HINTS.items():
            if keyword.lower() in title_lower:
                return hint
    return ""


def _format_with_suffix(value: float, suffix: str) -> str:
    """Format a numeric value with a recovered suffix.

    Avoids :g scientific notation and reconstructs K/M/B abbreviations
    from the raw numeric value (parse_number expands '220K' -> 220000.0).
    """
    if suffix in ("K", "k"):
        return f"{value / 1_000:.0f}K"
    if suffix in ("M", "m"):
        return f"{value / 1_000_000:.1f}M"
    if suffix in ("B", "b"):
        return f"{value / 1_000_000_000:.2f}B"
    if suffix == "%":
        return f"{value:.1f}%"
    # Plain number — choose precision by magnitude
    abs_v = abs(value)
    if abs_v >= 100:
        return f"{value:.1f}"
    if abs_v >= 1:
        return f"{value:.2f}"
    if abs_v == 0:
        return "0.00"
    return f"{value:.3f}"


def _format_value(
    value: float | int | None,
    raw: str | None,
    *,
    title: str = "",
) -> str:
    """Format a numeric forecast/previous/actual cell."""
    if value is None:
        return "–"
    suffix = _recover_suffix(raw, title)
    try:
        return _format_with_suffix(float(value), suffix)
    except (TypeError, ValueError):
        return f"{value}{suffix}"


# ----------------------------------------------------------------------
# Builder
# ----------------------------------------------------------------------
class MacroSectionsBuilder:
    """Builds deterministic macro sections from a ForexFactory AgentResult."""

    def __init__(self, *, year: int, month: int) -> None:
        self.year = year
        self.month = month

    # Public entry points ------------------------------------------------
    def build(self, ff_result: AgentResult | None) -> list[ReportSection]:
        """Return deterministic ReportSections (A, B, and C if alerts present)."""
        sections: list[ReportSection] = []
        if ff_result is None:
            return sections

        section_a = self._build_upcoming(ff_result)
        if section_a is not None:
            sections.append(section_a)

        section_b = self._build_section_b(ff_result)
        if section_b is not None:
            sections.append(section_b)

        sigma_alerts = (ff_result.extra or {}).get("sigma_alerts", [])
        section_c = self.build_alert_section(sigma_alerts)
        if section_c is not None:
            sections.append(section_c)

        return sections

    def build_alert_section(
        self, sigma_alerts_data: list[dict]
    ) -> ReportSection | None:
        """Build Section C from pre-serialized sigma alert dicts.

        Returns None when there are no alerts so callers can simply skip
        the section (no empty placeholder is rendered).
        """
        if not sigma_alerts_data:
            return None

        title = "C. 리뷰 권고: KCIF 보고서 검증 필요 항목"
        lines: list[str] = [
            "아래 지표는 최근 24개월 역사적 분포에서 통계적으로 유의미한 "
            "서프라이즈가 발생한 항목입니다.",
            "동일 기간 KCIF 보고서의 관련 수치를 교차 검토하시기 바랍니다.",
            "",
        ]

        for alert in sigma_alerts_data:
            ev = alert.get("event") or {}
            try:
                dt_utc = datetime.fromisoformat(ev["datetime_utc"])
            except (KeyError, TypeError, ValueError):
                continue
            kst_str = _to_kst_str(dt_utc, ev.get("raw_time"))
            title_text = ev.get("title", "") or ""
            actual_fmt = _format_value(
                ev.get("actual"), None, title=title_text
            )
            forecast_fmt = _format_value(
                ev.get("forecast"), None, title=title_text
            )
            z = float(alert.get("z", 0.0))
            direction = "▲" if z > 0 else "▼"
            label = alert.get("label", "")
            history_n = int(alert.get("history_n", 0))
            lines.append(
                f"- **{kst_str}** · {label} · {title_text} · "
                f"실제 {actual_fmt} vs 예상 {forecast_fmt} "
                f"({direction} {abs(z):.1f}σ, n={history_n})"
            )

        lines.append("")
        lines.append(
            "> 위 지표는 통계적으로 큰 서프라이즈가 발생한 항목입니다. "
            "동일 기간 KCIF 보고서의 관련 수치를 교차 검토하시기 바랍니다."
        )

        content = "\n".join(lines)
        return ReportSection(heading=title, content=content)

    def build_llm_context_digest(self, ff_result: AgentResult | None) -> str:
        """Return a compact textual digest of upcoming events + recent surprises."""
        if ff_result is None:
            return ""

        parts: list[str] = []

        upcoming_rows = self._collect_window_rows(ff_result)
        if upcoming_rows:
            parts.append("#### 향후 주요 발표 (다음 14일)")
            for ev in upcoming_rows:
                kst_str = _to_kst_str(ev["datetime_utc"], ev.get("raw_time"))
                country_label = _infer_country_label(
                    ev["country"], ev.get("title", "")
                )
                impact_label = IMPACT_LABELS_KOR.get(ev["impact"], ev["impact"])
                title_text = ev.get("title", "")
                forecast = _format_value(
                    ev.get("forecast"),
                    ev.get("forecast_raw"),
                    title=title_text,
                )
                previous = _format_value(
                    ev.get("previous"),
                    ev.get("previous_raw"),
                    title=title_text,
                )
                parts.append(
                    f"- {kst_str} | {country_label} | {title_text} | "
                    f"{impact_label} | 예상 {forecast} / 이전 {previous} "
                    f"[출처: ForexFactory]"
                )
        else:
            parts.append("#### 향후 주요 발표 (다음 14일)")
            parts.append("- 향후 14일 내 발표 예정 주요 지표 없음.")

        surprise_rows = self._collect_surprise_rows(ff_result)
        if surprise_rows:
            parts.append("")
            top_n = min(DIGEST_SURPRISE_TOP_N, len(surprise_rows))
            parts.append(f"#### 최근 서프라이즈 (상위 {top_n}건)")
            for ev in surprise_rows[:top_n]:
                dt_local = ev["datetime_utc"].astimezone(KST)
                date_str = f"{dt_local.month:02d}-{dt_local.day:02d}"
                country_label = _infer_country_label(
                    ev["country"], ev.get("title", "")
                )
                title_text = ev.get("title", "")
                actual_fmt = _format_value(
                    ev.get("actual"),
                    ev.get("actual_raw"),
                    title=title_text,
                )
                forecast_fmt = _format_value(
                    ev.get("forecast"),
                    ev.get("forecast_raw"),
                    title=title_text,
                )
                surprise = ev["surprise"]
                arrow = "▲" if surprise > 0 else ("▼" if surprise < 0 else "=")
                suffix = _recover_suffix(ev.get("actual_raw"), title_text)
                surprise_fmt = _format_with_suffix(abs(surprise), suffix)
                parts.append(
                    f"- {date_str} {country_label} · {title_text}: "
                    f"실제 {actual_fmt} vs 예상 {forecast_fmt} "
                    f"({arrow} {surprise_fmt}) [출처: ForexFactory]"
                )

        sigma_alerts = (ff_result.extra or {}).get("sigma_alerts", [])
        if sigma_alerts:
            parts.append("")
            parts.append(f"#### 리뷰 권고 ({len(sigma_alerts)}건)")
            for alert in sigma_alerts:
                ev = alert.get("event") or {}
                try:
                    dt_utc = datetime.fromisoformat(ev["datetime_utc"])
                except (KeyError, TypeError, ValueError):
                    continue
                kst_str = _to_kst_str(dt_utc, ev.get("raw_time"))
                title_text = ev.get("title", "") or ""
                actual_fmt = _format_value(
                    ev.get("actual"), None, title=title_text
                )
                forecast_fmt = _format_value(
                    ev.get("forecast"), None, title=title_text
                )
                z = float(alert.get("z", 0.0))
                direction = "▲" if z > 0 else "▼"
                label = alert.get("label", "")
                parts.append(
                    f"- {kst_str} · {label} · {title_text}: "
                    f"실제 {actual_fmt} vs 예상 {forecast_fmt} "
                    f"({direction} {abs(z):.1f}σ) — KCIF 보고서 교차 확인 필요"
                )

        return "\n".join(parts)

    # Section A ----------------------------------------------------------
    def _build_upcoming(self, ff_result: AgentResult) -> ReportSection | None:
        rows = self._collect_window_rows(ff_result)
        title = "A. ForexFactory 향후 거시 캘린더 (다음 14일)"

        body_lines: list[str] = []
        if not rows:
            body_lines.append("향후 14일 내 발표 예정 주요 지표 없음.")
            body_lines.append("")
        else:
            body_lines.append(
                "| 일시 (KST) | 국가 | 지표 | 중요도 | 예상치 | 이전치 |"
            )
            body_lines.append("|---|---|---|---|---|---|")
            for ev in rows:
                kst_str = _to_kst_str(ev["datetime_utc"], ev.get("raw_time"))
                country_label = _infer_country_label(
                    ev["country"], ev.get("title", "")
                )
                impact_label = IMPACT_LABELS_KOR.get(ev["impact"], ev["impact"])
                title_text = ev.get("title", "") or ""
                forecast = _format_value(
                    ev.get("forecast"),
                    ev.get("forecast_raw"),
                    title=title_text,
                )
                previous = _format_value(
                    ev.get("previous"),
                    ev.get("previous_raw"),
                    title=title_text,
                )
                title_md = title_text.replace("|", r"\|")
                body_lines.append(
                    f"| {kst_str} | {country_label} | {title_md} | "
                    f"{impact_label} | {forecast} | {previous} |"
                )
            body_lines.append("")

        body_lines.append(
            "*출처: ForexFactory JSON 피드 · 갱신주기 4시간 · 시각은 KST 기준 "
            "('종일'/'미정' 표기는 ET 기준 발표 시각 미확정)*"
        )
        body_lines.append(
            "*참고: ForexFactory의 EUR 표기는 유로존 통합 또는 회원국 지표를 "
            "모두 포함합니다 (지표 제목으로 식별)*"
        )

        content = "\n".join(body_lines)
        return ReportSection(heading=title, content=content)

    # Section B ----------------------------------------------------------
    def _build_section_b(self, ff_result: AgentResult) -> ReportSection | None:
        rows = self._collect_surprise_rows(ff_result)
        title = "B. ForexFactory 주요 지표 서프라이즈 (최근 30일)"

        body_lines: list[str] = []
        if not rows:
            body_lines.append("해당 기간 발표된 주요 유럽 지표가 없습니다.")
            body_lines.append("")
        else:
            body_lines.append(
                "| 일시 (KST) | 국가 | 지표 | 중요도 | 실제치 | 예상치 | 차이 |"
            )
            body_lines.append("|---|---|---|---|---|---|---|")
            for ev in rows[:SECTION_B_MAX_ROWS]:
                kst_str = _to_kst_str(ev["datetime_utc"], ev.get("raw_time"))
                country_label = _infer_country_label(
                    ev["country"], ev.get("title", "")
                )
                impact_label = IMPACT_LABELS_KOR.get(ev["impact"], ev["impact"])
                title_text = ev.get("title", "") or ""
                actual = _format_value(
                    ev.get("actual"),
                    ev.get("actual_raw"),
                    title=title_text,
                )
                forecast = _format_value(
                    ev.get("forecast"),
                    ev.get("forecast_raw"),
                    title=title_text,
                )
                surprise = ev["surprise"]
                if surprise > 0:
                    arrow = "▲"
                elif surprise < 0:
                    arrow = "▼"
                else:
                    arrow = "="
                suffix = _recover_suffix(ev.get("actual_raw"), title_text)
                surprise_fmt = _format_with_suffix(abs(surprise), suffix)
                title_md = title_text.replace("|", r"\|")
                body_lines.append(
                    f"| {kst_str} | {country_label} | {title_md} | "
                    f"{impact_label} | {actual} | {forecast} | "
                    f"{arrow} {surprise_fmt} |"
                )
            body_lines.append("")

        body_lines.append(
            "*출처: ForexFactory JSON 피드 · 실제치 발표 기준*"
        )
        body_lines.append(
            "*참고: ForexFactory의 EUR 표기는 유로존 통합 또는 회원국 지표를 "
            "모두 포함합니다 (지표 제목으로 식별)*"
        )

        content = "\n".join(body_lines)
        return ReportSection(heading=title, content=content)

    # Internals ----------------------------------------------------------
    def _collect_window_rows(self, ff_result: AgentResult) -> list[dict]:
        """Collect filtered, sorted upcoming events as plain dicts."""
        events_by_period = (ff_result.extra or {}).get("events_by_period", {})
        candidates: list[dict] = []
        for period in ("thisweek", "nextweek"):
            for d in events_by_period.get(period, []) or []:
                candidates.append(d)

        now_utc = datetime.now(UTC)
        if (now_utc.year, now_utc.month) == (self.year, self.month):
            window_start = now_utc
        else:
            window_start = datetime(self.year, self.month, 1, tzinfo=UTC)
        window_end = window_start + timedelta(days=WINDOW_DAYS)

        seen_ids: set[str] = set()
        rows: list[dict] = []
        for d in candidates:
            event_id = d.get("event_id")
            if event_id and event_id in seen_ids:
                continue

            dt_raw = d.get("datetime_utc")
            try:
                dt = datetime.fromisoformat(dt_raw) if dt_raw else None
            except (TypeError, ValueError):
                continue
            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)

            impact = d.get("impact") or ""
            country = d.get("country") or ""
            if impact in EXCLUDED_IMPACTS:
                continue
            if impact not in ALLOWED_IMPACTS:
                continue
            if country not in EUROPE_FOCUS_COUNTRIES:
                continue
            if not (window_start <= dt < window_end):
                continue

            if event_id:
                seen_ids.add(event_id)

            rows.append(
                {
                    "datetime_utc": dt,
                    "country": country,
                    "title": d.get("title", ""),
                    "impact": impact,
                    "forecast": d.get("forecast"),
                    "previous": d.get("previous"),
                    "raw_time": d.get("raw_time"),
                    "forecast_raw": d.get("forecast_raw"),
                    "previous_raw": d.get("previous_raw"),
                }
            )

        rows.sort(key=lambda r: r["datetime_utc"])
        return rows[:MAX_ROWS]

    def _collect_surprise_rows(self, ff_result: AgentResult) -> list[dict]:
        """Collect released European events with non-null surprise.

        Window: [anchor_start − 30d, anchor_start + 7d] where anchor_start
        is the first day of the report month (UTC). Sorted by absolute
        surprise magnitude, descending.

        Sources (in priority order):
        1. DB released events queried by ForexFactoryAgent (authoritative,
           covers the full lookback window even when "lastweek" JSON 404s).
        2. events_by_period["lastweek"/"thisweek"] as a fallback supplement.
        """
        extra = ff_result.extra or {}
        candidates: list[dict] = []

        # Primary: DB-backed released events (already filtered for the window).
        for d in extra.get("released_events_db", []) or []:
            candidates.append(d)

        # Supplement with any released events from the JSON feeds that might
        # not have been persisted to DB yet (e.g. same-day fetches).
        events_by_period = extra.get("events_by_period", {})
        for period in ("lastweek", "thisweek"):
            for d in events_by_period.get(period, []) or []:
                candidates.append(d)

        anchor_start = datetime(self.year, self.month, 1, tzinfo=UTC)
        window_start = anchor_start - timedelta(days=SECTION_B_LOOKBACK_DAYS)
        window_end = anchor_start + timedelta(days=SECTION_B_LOOKAHEAD_DAYS)

        seen_ids: set[str] = set()
        rows: list[dict] = []
        for d in candidates:
            event_id = d.get("event_id")
            if event_id and event_id in seen_ids:
                continue

            if not d.get("is_released"):
                continue

            actual = d.get("actual")
            forecast = d.get("forecast")
            if actual is None or forecast is None:
                continue

            impact = d.get("impact") or ""
            country = d.get("country") or ""
            if impact in EXCLUDED_IMPACTS:
                continue
            if impact not in ALLOWED_IMPACTS:
                continue
            if country not in EUROPE_FOCUS_COUNTRIES:
                continue

            dt_raw = d.get("datetime_utc")
            try:
                dt = datetime.fromisoformat(dt_raw) if dt_raw else None
            except (TypeError, ValueError):
                continue
            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            if not (window_start <= dt <= window_end):
                continue

            if event_id:
                seen_ids.add(event_id)

            try:
                surprise = float(actual) - float(forecast)
            except (TypeError, ValueError):
                continue

            rows.append(
                {
                    "datetime_utc": dt,
                    "country": country,
                    "title": d.get("title", ""),
                    "impact": impact,
                    "actual": actual,
                    "forecast": forecast,
                    "previous": d.get("previous"),
                    "raw_time": d.get("raw_time"),
                    "actual_raw": d.get("actual_raw"),
                    "forecast_raw": d.get("forecast_raw"),
                    "previous_raw": d.get("previous_raw"),
                    "surprise": surprise,
                }
            )

        rows.sort(key=lambda r: abs(r["surprise"]), reverse=True)
        return rows
