"""Deterministic numeric audit for euro-macro research reports.

Sibling of :mod:`indepth_analysis.temporal_lint`: a fast, network-free,
LLM-free screen that flags numbers the report *cites in prose* which
contradict what our own stores actually hold — the "the model invented a
plausible-looking figure" failure mode (e.g. writing the euro-area
unemployment rate as 5.1% when the calendar actual is 6.3%).

Design constraints that keep the false-positive rate survivable:

1. **Curated registry, never a generic parser.** Only the indicators in
   :data:`INDICATOR_REGISTRY` are audited, and every alias is *multi-token*
   with a country/region qualifier ("유로존 실업률", "ECB 예금금리"). A euro
   report cites the same indicator for five countries in the same paragraph,
   so a bare "실업률" alias would mis-assign country and manufacture noise.
2. **Unit-class discipline.** A ``%`` level, a ``%p`` change, a ``bp`` move and
   a bare index level are different things. Each spec declares the unit class
   it accepts; everything else near the alias is ignored, not compared.
   ``조/억/만`` magnitudes and range expressions (``1.5~2.0%``) are dropped
   outright — they are pure false-positive vectors.
3. **LLM prose only.** Deterministic sections (A/B/G/H, 부록 I/IV/VI, 출처
   목록, 참고문헌, 목차) are rendered *from* these same stores, so re-checking
   them against the stores is circular. They are skipped, as are markdown
   table rows.
4. **Charitable matching, line-scoped.** All unit-compatible numbers in a short
   window after the alias are collected, and the reference is additionally
   acquitted if it appears anywhere on the same line. This absorbs
   "2.00%에서 2.25%로" transitions and "2025년 저점 2.00% → 첫 인상(2.25%)"
   narratives. Acquittal never crosses lines: a report may cite an indicator
   correctly in one paragraph and wrongly in the next, and both are judged
   independently.
5. **Stale references cannot convict.** If the reference observation is older
   than :data:`MAX_REF_AGE_DAYS` (or carries no usable date), a mismatch is
   reported as INFO, not HIGH — the store is behind the report, which is not
   evidence the report is wrong.

The result is **advisory**. Nothing here raises, and nothing here blocks a
publish — unlike :func:`temporal_lint.assert_no_high`, there is deliberately
no gate helper. HIGH means "a human should look", not "this is wrong".

Measured on the existing ``reports/euro_macro/*.md`` corpus (12 reports): 0
HIGH findings, 19 INFO (all genuine store-coverage gaps); both members of a
two-error injection test were caught as HIGH.

Public API::

    findings = scan_numeric_issues(text, as_of=date.today(), sources=srcs)
    print(render_report(findings))
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "INDICATOR_REGISTRY",
    "Citation",
    "IndicatorSpec",
    "MacroStoreSource",
    "NumericFinding",
    "OptionsdeckSource",
    "RefValue",
    "ReferenceSource",
    "auditable_lines",
    "build_default_sources",
    "extract_citations",
    "render_report",
    "scan_numeric_issues",
]

# --------------------------------------------------------------------------
# tunables
# --------------------------------------------------------------------------

#: Max characters allowed between two alias tokens ("유로존" … "HICP").
#: Sized from real reports: "유로존 5월 연간 인플레이션(HICP)" needs ~13.
ALIAS_GAP = 16

#: Characters after the alias in which a cited number may *start*. A slightly
#: longer slice is read so a number straddling the boundary is not truncated
#: (truncating "-0.13%" into "-0" manufactured implausible-value alarms).
CITE_WINDOW = 30
_WINDOW_SLACK = 12

#: A reference older than this (relative to the audit as-of date) can no longer
#: contradict a fresh print — the finding is downgraded to INFO instead.
MAX_REF_AGE_DAYS = 120

#: The first number must begin within this many chars of the alias end,
#: otherwise it is not plausibly "the number for this indicator".
FIRST_NUM_OFFSET = 12

#: Forecast/projection cues immediately *before* an alias suppress the match:
#: a projected 2027 figure is not a claim about the current print.
_FORECAST_CUES: tuple[str, ...] = (
    "전망",
    "예상",
    "예측",
    "추정",
    "컨센서스",
    "목표",
    "가정",
    "시나리오",
    "서베이",
    "forecast",
    "projection",
)
_FORECAST_LOOKBEHIND = 25

# --------------------------------------------------------------------------
# lexical primitives
# --------------------------------------------------------------------------

# Gap between alias tokens. Must not cross a line, a completed figure (%), a
# citation bracket, or a sentence boundary marker.
_GAP_CLASS = r"[^\n%％\[\]。]"

_NUMBER = r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?"

# Order matters: %p before %, bps before bp.
_UNIT = (
    r"(?:%p|％p|%포인트|퍼센트포인트|bps|bp|베이시스포인트|포인트|pt"
    r"|%|％|달러|엔|위안|파운드|원|배|조|억|만|천|명"
    r"|개월|분기|주간|주래|주|년래|년|월|일|시|개|건|회|차|위)?"
)

_NUM_UNIT_RE = re.compile(rf"({_NUMBER})\s*({_UNIT})")

#: A number touching one of these is part of a range ("1.5~2.0%"), a date
#: ("4/16") or a fraction — never a standalone cited level.
_SPLIT_CHARS = "~∼〜–—/"

# Unit classes.
PCT = "pct"  # 3.2%          → a level in percent
PP = "pp"  # 0.3%p         → a change in percentage points
BP = "bp"  # 25bp          → a change in basis points
LEVEL = "level"  # 49.5, 1.1573달러 → index / FX level
MAGNITUDE = "magnitude"  # 1,107.5만 명   → never audited
ORDINAL = "ordinal"  # 2026년, 2분기  → never audited

_UNIT_CLASS: dict[str, str] = {
    "%p": PP,
    "％p": PP,
    "%포인트": PP,
    "퍼센트포인트": PP,
    "포인트": PP,
    "pt": PP,
    "bp": BP,
    "bps": BP,
    "베이시스포인트": BP,
    "%": PCT,
    "％": PCT,
    "": LEVEL,
    "달러": LEVEL,
    "엔": LEVEL,
    "위안": LEVEL,
    "파운드": LEVEL,
    "원": LEVEL,
    "조": MAGNITUDE,
    "억": MAGNITUDE,
    "만": MAGNITUDE,
    "천": MAGNITUDE,
    "명": MAGNITUDE,
    "배": MAGNITUDE,
    "개": MAGNITUDE,
    "건": MAGNITUDE,
    "년": ORDINAL,
    "월": ORDINAL,
    "분기": ORDINAL,
    "일": ORDINAL,
    "회": ORDINAL,
    "차": ORDINAL,
    "위": ORDINAL,
    "개월": ORDINAL,
    "주": ORDINAL,
    "주간": ORDINAL,
    "주래": ORDINAL,
    "년래": ORDINAL,
    "시": ORDINAL,
}

#: Which citation unit classes each spec unit will accept.
_ACCEPTED: dict[str, frozenset[str]] = {
    "%": frozenset({PCT}),
    "%p": frozenset({PP}),
    "bp": frozenset({BP}),
    "level": frozenset({LEVEL}),
}


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    """One auditable indicator.

    ``aliases`` are space-separated *token phrases*; tokens are matched in
    order with up to :data:`ALIAS_GAP` chars between them, so "수신금리 DFR"
    matches "수신금리(DFR)". Every alias must carry a country/region qualifier
    (enforced: at least two tokens, or a ``/`` currency pair).

    ``source_kind`` / ``series_key`` name exactly where the reference value is
    read from:

    ==============  ==========================================================
    ``source_kind``  reference lookup
    ==============  ==========================================================
    ``rate``         ``MacroStore.get_rate_history(series_key)`` — policy rate,
                     ``series_key`` is the currency code (``"EUR"``…)
    ``fx``           ``MacroStore.get_fx_snapshot(base, [quote])`` —
                     ``series_key`` is ``"BASE/QUOTE"``
    ``calendar``     ``MacroStore.query_events(country, title=series_key)``
                     latest released ``actual`` (exact title match)
    ``series``       ``OptionsdeckSeriesClient.get_series(series_key, …)``
    ==============  ==========================================================

    ``fallback`` is an optional second ``(source_kind, series_key)`` tried when
    the primary store has nothing — used to reach the optionsdeck long-history
    series for indicators whose calendar coverage is thin.
    """

    key: str
    label: str
    aliases: tuple[str, ...]
    country: str
    unit: str  # "%" | "%p" | "bp" | "level"
    lo: float
    hi: float
    source_kind: str  # "rate" | "fx" | "calendar" | "series"
    series_key: str
    tol_abs: float | None = None  # absolute tolerance; None → relative tol_pct
    reject_between: tuple[str, ...] = ()  # tokens forbidden inside the alias gap
    reject_after: tuple[str, ...] = ()  # tokens forbidden right after the alias
    fallback: tuple[str, str] | None = None
    note: str = ""


INDICATOR_REGISTRY: tuple[IndicatorSpec, ...] = (
    # ── 물가 ────────────────────────────────────────────────────────────
    IndicatorSpec(
        key="ea_hicp",
        label="유로존 HICP(헤드라인, YoY)",
        aliases=(
            "유로존 HICP",
            "유로존 소비자물가",
            "유로존 인플레이션",
            "유로존 물가상승률",
            "유로존 CPI",
            "유로지역 HICP",
            "euro area HICP",
            "eurozone HICP",
        ),
        country="EUR",
        unit="%",
        lo=-2.0,
        hi=15.0,
        source_kind="calendar",
        series_key="CPI Flash Estimate y/y",
        tol_abs=0.15,
        reject_between=("근원", "코어", "core", "기조"),
        fallback=("series", "M.RCH_A.CP00.EA"),
        note="FF 'CPI Flash Estimate y/y' actual / optionsdeck EA HICP YoY",
    ),
    IndicatorSpec(
        key="ea_hicp_core",
        label="유로존 근원 HICP(YoY)",
        aliases=(
            "유로존 근원 HICP",
            "유로존 코어 HICP",
            "유로존 근원물가",
            "유로존 근원 인플레이션",
            "유로존 근원 CPI",
            "유로존 코어 CPI",
        ),
        country="EUR",
        unit="%",
        lo=-2.0,
        hi=15.0,
        source_kind="calendar",
        series_key="Core CPI Flash Estimate y/y",
        tol_abs=0.15,
        note="FF 'Core CPI Flash Estimate y/y' actual",
    ),
    # ── 고용 ────────────────────────────────────────────────────────────
    IndicatorSpec(
        key="ea_unemployment",
        label="유로존 실업률",
        aliases=(
            "유로존 실업률",
            "유로존 실업율",
            "유로지역 실업률",
            "euro area unemployment rate",
            "eurozone unemployment rate",
        ),
        country="EUR",
        unit="%",
        lo=2.0,
        hi=30.0,
        source_kind="calendar",
        series_key="Unemployment Rate",
        tol_abs=0.15,
        reject_between=("청년", "여성", "남성", "25세", "장기"),
        note="FF EUR 'Unemployment Rate' actual",
    ),
    IndicatorSpec(
        key="es_unemployment",
        label="스페인 실업률",
        aliases=("스페인 실업률", "스페인 실업율"),
        country="EUR",
        unit="%",
        lo=2.0,
        hi=35.0,
        source_kind="calendar",
        series_key="Spanish Unemployment Rate",
        tol_abs=0.2,
        reject_between=("청년", "여성", "남성"),
        note="FF EUR 'Spanish Unemployment Rate' actual",
    ),
    # ── 정책금리 ────────────────────────────────────────────────────────
    IndicatorSpec(
        key="ecb_dfr",
        label="ECB 예금금리(DFR)",
        aliases=(
            "ECB 예금금리",
            "ECB 수신금리",
            "ECB 정책금리",
            "ECB 기준금리",
            "예금금리 DFR",
            "수신금리 DFR",
            "정책금리 DFR",
            "ECB DFR",
        ),
        country="EUR",
        unit="%",
        lo=-1.0,
        hi=8.0,
        source_kind="rate",
        series_key="EUR",
        tol_abs=0.1,
        reject_between=("MRO", "MLF", "리파이낸싱", "한계대출"),
        note="MacroStore.rate_decisions['EUR'] (FRED ECBDFR)",
    ),
    IndicatorSpec(
        key="fed_funds",
        label="미 연방기금금리",
        aliases=(
            "미국 정책금리",
            "미국 기준금리",
            "미 정책금리",
            "미 기준금리",
            "연준 정책금리",
            "연준 기준금리",
            "연방기금 금리",
            "Fed 정책금리",
        ),
        country="USD",
        unit="%",
        lo=0.0,
        hi=12.0,
        source_kind="rate",
        series_key="USD",
        tol_abs=0.15,
        fallback=("series", "FEDFUNDS"),
        note="MacroStore.rate_decisions['USD'] (FRED FEDFUNDS)",
    ),
    IndicatorSpec(
        key="boe_rate",
        label="영란은행 정책금리",
        aliases=(
            "영국 정책금리",
            "영국 기준금리",
            "BoE 정책금리",
            "BoE 기준금리",
            "영란은행 정책금리",
            "영란은행 기준금리",
        ),
        country="GBP",
        unit="%",
        lo=0.0,
        hi=12.0,
        source_kind="rate",
        series_key="GBP",
        tol_abs=0.15,
        note="MacroStore.rate_decisions['GBP'] (OECD MEI immediate rate)",
    ),
    IndicatorSpec(
        key="boj_rate",
        label="일본은행 정책금리",
        aliases=(
            "일본 정책금리",
            "일본 기준금리",
            "BoJ 정책금리",
            "BOJ 기준금리",
            "일본은행 정책금리",
        ),
        country="JPY",
        unit="%",
        lo=-1.0,
        hi=6.0,
        source_kind="rate",
        series_key="JPY",
        tol_abs=0.15,
        note="MacroStore.rate_decisions['JPY']",
    ),
    IndicatorSpec(
        key="bok_rate",
        label="한국은행 기준금리",
        aliases=(
            "한국 정책금리",
            "한국 기준금리",
            "한은 기준금리",
            "한은 정책금리",
            "BoK 정책금리",
        ),
        country="KRW",
        unit="%",
        lo=0.0,
        hi=12.0,
        source_kind="rate",
        series_key="KRW",
        tol_abs=0.15,
        note="MacroStore.rate_decisions['KRW']",
    ),
    # ── 환율 ────────────────────────────────────────────────────────────
    IndicatorSpec(
        key="eurusd",
        label="EUR/USD",
        aliases=("EUR/USD", "유로/달러", "유로 달러 환율", "EURUSD 환율"),
        country="EUR",
        unit="level",
        lo=0.7,
        hi=1.8,
        source_kind="fx",
        series_key="EUR/USD",
        note="MacroStore.fx_rates(EUR→USD, frankfurter/ECB)",
    ),
    IndicatorSpec(
        key="eurkrw",
        label="EUR/KRW",
        aliases=("EUR/KRW", "유로/원", "유로 원화 환율", "유로 원 환율"),
        country="EUR",
        unit="level",
        lo=900.0,
        hi=2500.0,
        source_kind="fx",
        series_key="EUR/KRW",
        note="MacroStore.fx_rates(EUR→KRW, frankfurter/yfinance)",
    ),
    # ── 성장 ────────────────────────────────────────────────────────────
    IndicatorSpec(
        key="ea_gdp_qoq",
        label="유로존 GDP(전기비)",
        aliases=("유로존 GDP", "유로존 성장률", "유로지역 GDP"),
        country="EUR",
        unit="%",
        lo=-15.0,
        hi=15.0,
        source_kind="calendar",
        series_key="Prelim Flash GDP q/q",
        tol_abs=0.2,
        reject_between=("전년", "연간", "YoY", "y/y", "적자", "부채", "재정"),
        reject_after=("대비", "의"),
        note="FF EUR 'Prelim Flash GDP q/q' actual",
    ),
    IndicatorSpec(
        key="de_gdp_qoq",
        label="독일 GDP(전기비)",
        aliases=("독일 GDP", "독일 성장률", "독일 실질 GDP"),
        country="EUR",
        unit="%",
        lo=-15.0,
        hi=15.0,
        source_kind="calendar",
        series_key="German Prelim GDP q/q",
        tol_abs=0.2,
        reject_between=("전년", "연간", "YoY", "y/y", "적자", "부채", "재정"),
        reject_after=("대비", "의"),
        fallback=("series", "evt.dbnomics.Eurostat/teina011/Q.B1GQ.PCH_Q1_SCA.DE"),
        note="FF EUR 'German Prelim GDP q/q' actual",
    ),
    IndicatorSpec(
        key="fr_gdp_qoq",
        label="프랑스 GDP(전기비)",
        aliases=("프랑스 GDP", "프랑스 성장률", "프랑스 실질 GDP"),
        country="EUR",
        unit="%",
        lo=-15.0,
        hi=15.0,
        source_kind="calendar",
        series_key="French Flash GDP q/q",
        tol_abs=0.2,
        reject_between=("전년", "연간", "YoY", "y/y", "적자", "부채", "재정"),
        reject_after=("대비", "의"),
        note="FF EUR 'French Flash GDP q/q' actual",
    ),
    IndicatorSpec(
        key="it_gdp_qoq",
        label="이탈리아 GDP(전기비)",
        aliases=("이탈리아 GDP", "이탈리아 성장률", "이탈리아 실질 GDP"),
        country="EUR",
        unit="%",
        lo=-15.0,
        hi=15.0,
        source_kind="calendar",
        series_key="Italian Prelim GDP q/q",
        tol_abs=0.2,
        reject_between=("전년", "연간", "YoY", "y/y", "적자", "부채", "재정"),
        reject_after=("대비", "의"),
        note="FF EUR 'Italian Prelim GDP q/q' actual",
    ),
    IndicatorSpec(
        key="es_gdp_qoq",
        label="스페인 GDP(전기비)",
        aliases=("스페인 GDP", "스페인 성장률", "스페인 실질 GDP"),
        country="EUR",
        unit="%",
        lo=-15.0,
        hi=15.0,
        source_kind="calendar",
        series_key="Spanish Flash GDP q/q",
        tol_abs=0.2,
        reject_between=("전년", "연간", "YoY", "y/y", "적자", "부채", "재정"),
        reject_after=("대비", "의"),
        note="FF EUR 'Spanish Flash GDP q/q' actual",
    ),
    # ── PMI ─────────────────────────────────────────────────────────────
    IndicatorSpec(
        key="ea_pmi_mfg",
        label="유로존 제조업 PMI",
        aliases=("유로존 제조업 PMI", "유로지역 제조업 PMI"),
        country="EUR",
        unit="level",
        lo=25.0,
        hi=75.0,
        source_kind="calendar",
        series_key="Final Manufacturing PMI",
        tol_abs=0.5,
        note="FF EUR 'Final Manufacturing PMI' actual",
    ),
    IndicatorSpec(
        key="ea_pmi_svc",
        label="유로존 서비스업 PMI",
        aliases=("유로존 서비스 PMI", "유로존 서비스업 PMI"),
        country="EUR",
        unit="level",
        lo=25.0,
        hi=75.0,
        source_kind="calendar",
        series_key="Final Services PMI",
        tol_abs=0.5,
        note="FF EUR 'Final Services PMI' actual",
    ),
    IndicatorSpec(
        key="ea_pmi_comp",
        label="유로존 종합 PMI",
        aliases=("유로존 종합 PMI", "유로존 컴포지트 PMI", "유로존 합성 PMI"),
        country="EUR",
        unit="level",
        lo=25.0,
        hi=75.0,
        source_kind="calendar",
        series_key="Final Composite PMI",
        tol_abs=0.5,
        note="FF EUR 'Final Composite PMI' actual (커버리지 얇음 → 대개 INFO)",
    ),
)


def _validate_registry(specs: tuple[IndicatorSpec, ...]) -> list[str]:
    """Return alias-policy violations (bare single-token aliases)."""
    bad: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        if spec.key in seen:
            bad.append(f"{spec.key}: 중복 key")
        seen.add(spec.key)
        if spec.unit not in _ACCEPTED:
            bad.append(f"{spec.key}: 알 수 없는 unit {spec.unit!r}")
        for alias in spec.aliases:
            tokens = alias.split()
            if len(tokens) < 2 and "/" not in alias:
                bad.append(f"{spec.key}: bare alias {alias!r} (국가/지역 수식어 필요)")
    return bad


# --------------------------------------------------------------------------
# reference sources
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefValue:
    """An authoritative value pulled from one of our own stores."""

    value: float
    as_of: date | None
    source: str
    key: str


@runtime_checkable
class ReferenceSource(Protocol):
    """A store that can answer "what was this indicator, as of X?"."""

    name: str
    handles: frozenset[str]

    def available(self) -> bool: ...

    def lookup(self, spec: IndicatorSpec, as_of: date) -> RefValue | None: ...


class MacroStoreSource:
    """Reference values from the local bgilib ``MacroStore`` calendar DB."""

    name = "macro_store"
    handles = frozenset({"rate", "fx", "calendar"})

    def __init__(
        self,
        store: object | None = None,
        *,
        db_path: Path | str = Path("data/macro_calendar.db"),
    ) -> None:
        self._store = store
        self._db_path = Path(db_path)
        self._tried = store is not None

    # -- plumbing --

    def _get_store(self) -> object | None:
        if self._store is None and not self._tried:
            self._tried = True
            try:
                from bgilib.macro.storage import MacroStore

                if self._db_path.exists():
                    self._store = MacroStore(self._db_path)
            except Exception:  # pragma: no cover - env-dependent
                self._store = None
        return self._store

    def available(self) -> bool:
        return self._get_store() is not None

    # -- lookup --

    def lookup(self, spec: IndicatorSpec, as_of: date) -> RefValue | None:
        store = self._get_store()
        if store is None:
            return None
        try:
            if spec.source_kind == "rate":
                return self._lookup_rate(store, spec, as_of)
            if spec.source_kind == "fx":
                return self._lookup_fx(store, spec, as_of)
            if spec.source_kind == "calendar":
                return self._lookup_calendar(store, spec, as_of)
        except Exception:
            return None
        return None

    def _lookup_rate(self, store, spec: IndicatorSpec, as_of: date) -> RefValue | None:
        history = store.get_rate_history(spec.series_key, until=as_of)
        if not history:
            return None
        last = history[-1]
        return RefValue(
            value=float(last.rate_pct),
            as_of=last.date_utc,
            source=f"{self.name}:rate_decisions",
            key=spec.series_key,
        )

    def _lookup_fx(self, store, spec: IndicatorSpec, as_of: date) -> RefValue | None:
        base, _, quote = spec.series_key.partition("/")
        rows = store.get_fx_snapshot(base, [quote], as_of=as_of)
        if not rows:
            return None
        fx = rows[0]
        return RefValue(
            value=float(fx.rate),
            as_of=fx.date_utc,
            source=f"{self.name}:fx_rates",
            key=spec.series_key,
        )

    def _lookup_calendar(
        self, store, spec: IndicatorSpec, as_of: date
    ) -> RefValue | None:
        until = datetime.combine(as_of + timedelta(days=1), datetime.min.time(), UTC)
        events = store.query_events(
            country=spec.country, title=spec.series_key, until=until
        )
        # query_events uses LIKE '%title%'; re-filter to an exact title so a
        # 'Core CPI Flash Estimate y/y' row can never answer for
        # 'CPI Flash Estimate y/y'.
        hits = [
            e
            for e in events
            if e.title == spec.series_key and getattr(e, "actual", None) is not None
        ]
        if not hits:
            return None
        last = max(hits, key=lambda e: e.datetime_utc)
        return RefValue(
            value=float(last.actual),
            as_of=last.datetime_utc.date(),
            source=f"{self.name}:calendar_events",
            key=spec.series_key,
        )


class OptionsdeckSource:
    """Reference values from the optionsdeck macro series snapshot (T1 adapter).

    Deliberately duck-typed: the adapter
    (``indepth_analysis.data.optionsdeck_series.OptionsdeckSeriesClient``) is
    developed in parallel, so this class only assumes ``get_series(series_id,
    start, end)`` returning date/value pairs and an optional ``available()``.
    If the module is missing, the client cannot be built, or the call raises,
    the source silently reports itself unavailable and is skipped.
    """

    name = "optionsdeck"
    handles = frozenset({"series"})

    def __init__(self, client: object) -> None:
        self._client = client

    @classmethod
    def create(cls) -> OptionsdeckSource | None:
        """Build the source, or return ``None`` if the adapter is unavailable."""
        try:
            from indepth_analysis.data.optionsdeck_series import (  # noqa: I001
                OptionsdeckSeriesClient,
            )
        except Exception:
            return None
        try:
            client = OptionsdeckSeriesClient()
        except Exception:  # pragma: no cover - env-dependent
            return None
        src = cls(client)
        return src if src.available() else None

    def available(self) -> bool:
        probe = getattr(self._client, "available", None)
        if probe is None:
            return True
        try:
            return bool(probe())
        except Exception:
            return False

    def lookup(self, spec: IndicatorSpec, as_of: date) -> RefValue | None:
        getter = getattr(self._client, "get_series", None)
        if getter is None:
            return None
        # Period labels are heterogeneous per series ("2026-07-27", "2026-07",
        # "2025-Q3"), and the adapter range-filters them lexicographically. So
        # fetch the whole series and do the as-of cut here, on parsed dates.
        try:
            rows = getter(spec.series_key)
        except TypeError:
            try:
                rows = getter(spec.series_key, None, as_of.isoformat())
            except Exception:
                return None
        except Exception:
            return None
        pairs = [
            (d, v) for d, v in _observation_pairs(rows) if d is not None and d <= as_of
        ]
        if not pairs:
            return None
        obs_date, value = pairs[-1]
        return RefValue(
            value=value,
            as_of=obs_date,
            source=f"{self.name}:macro_series",
            key=spec.series_key,
        )


_QUARTER_RE = re.compile(r"^(\d{4})-?Q([1-4])$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_obs_date(raw: str) -> date | None:
    """Parse the date labels macro series use: ISO, ``2025-12``, ``2025-Q3``.

    Period labels resolve to the *end* of the period, which is what a staleness
    check should compare against.
    """
    raw = raw.strip()
    q = _QUARTER_RE.match(raw)
    if q:
        year, quarter = int(q.group(1)), int(q.group(2))
        month = quarter * 3
        day = 31 if month in (3, 12) else 30
        return date(year, month, day)
    m = _MONTH_RE.match(raw)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        nxt = date(year + (month == 12), (month % 12) + 1, 1)
        return nxt - timedelta(days=1)
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _observation_pairs(rows: object) -> list[tuple[date | None, float]]:
    """Normalise whatever the adapter returns into ``(date, value)`` pairs."""
    out: list[tuple[date | None, float]] = []
    try:
        iterator = list(rows)  # type: ignore[arg-type]
    except TypeError:
        return out
    for row in iterator:
        obs_date: date | None = None
        value: float | None = None
        if isinstance(row, dict):
            raw_date, raw_value = row.get("date"), row.get("value")
        elif hasattr(row, "value"):
            raw_date, raw_value = getattr(row, "date", None), row.value
        elif isinstance(row, (tuple, list)) and len(row) >= 2:
            raw_date, raw_value = row[0], row[1]
        else:
            continue
        if isinstance(raw_date, date):
            obs_date = raw_date
        elif isinstance(raw_date, str):
            obs_date = _parse_obs_date(raw_date)
        try:
            value = float(raw_value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        out.append((obs_date, value))
    out.sort(key=lambda p: (p[0] is not None, p[0] or date.min))
    return out


def build_default_sources(
    *, db_path: Path | str = Path("data/macro_calendar.db")
) -> list[ReferenceSource]:
    """MacroStore + (if the T1 adapter exists) the optionsdeck snapshot."""
    sources: list[ReferenceSource] = []
    macro = MacroStoreSource(db_path=db_path)
    if macro.available():
        sources.append(macro)
    optionsdeck = OptionsdeckSource.create()
    if optionsdeck is not None:
        sources.append(optionsdeck)
    return sources


# --------------------------------------------------------------------------
# scoping — which lines are LLM prose
# --------------------------------------------------------------------------

# Deterministic sections are rendered *from* the same stores; auditing them
# against those stores is circular, so they are skipped entirely.
_SKIP_HEADER_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^[A-H]\.\s"),  # 결정론적 매크로 섹션 A~H
    re.compile(r"^부록\s+(I|IV|VI)\.?(?:\s|$)"),  # 부록 I / IV / VI
    re.compile(
        r"^(목차|출처\s*목록|참고\s*자료|참고\s*문헌|참고문헌|정량\s*데이터"
        r"|Sources?|References?|Appendix\s+(I|IV|VI)\b)"
    ),
)


def _is_skipped_header(heading: str) -> bool:
    text = heading.strip()
    return any(rx.match(text) for rx in _SKIP_HEADER_RES)


def auditable_lines(text: str) -> list[tuple[int, str]]:
    """Return ``(line_no, line)`` for LLM-prose lines worth auditing.

    Drops deterministic sections (by ``##`` heading), markdown table rows,
    fenced code/JSON blocks, and heading lines themselves.
    """
    out: list[tuple[int, str]] = []
    skipping = False
    in_fence = False
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith("## "):
            skipping = _is_skipped_header(stripped[3:])
            continue
        if stripped.startswith("#"):
            continue
        if skipping or not stripped:
            continue
        if stripped.startswith("|"):  # 표 = 결정론적/구조화 데이터
            continue
        out.append((i, line))
    return out


# --------------------------------------------------------------------------
# citation extraction
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Citation:
    """One number the report attributes to an indicator."""

    spec_key: str
    line_no: int
    value: float
    unit_class: str
    alias: str
    snippet: str


_ALIAS_CACHE: dict[str, re.Pattern[str]] = {}


def _alias_pattern(alias: str) -> re.Pattern[str]:
    cached = _ALIAS_CACHE.get(alias)
    if cached is None:
        tokens = [re.escape(t) for t in alias.split()]
        gap = rf"{_GAP_CLASS}{{0,{ALIAS_GAP}}}?"
        cached = re.compile(gap.join(tokens), re.IGNORECASE)
        _ALIAS_CACHE[alias] = cached
    return cached


def _classify(unit: str) -> str:
    return _UNIT_CLASS.get(unit.lower() if unit.isascii() else unit, LEVEL)


def _numbers_after(
    window: str, *, max_start: int | None = None
) -> list[tuple[float, str, int]]:
    """All ``(value, unit_class, start)`` numbers in a post-alias window."""
    out: list[tuple[float, str, int]] = []
    for m in _NUM_UNIT_RE.finditer(window):
        start = m.start(1)
        if max_start is not None and start > max_start:
            break
        # range expression ("1.5~2.0%") or date/fraction ("4/16") → not a level
        if start > 0 and window[start - 1] in _SPLIT_CHARS:
            continue
        after = window[m.end()] if m.end() < len(window) else ""
        if after in _SPLIT_CHARS and after:
            continue
        # unrecognised trailing unit ("-18pips", "3bn") → not comparable
        if not m.group(2) and after.isascii() and after.isalpha():
            continue
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        out.append((value, _classify(m.group(2) or ""), start))
    return out


def extract_citations(
    line: str,
    line_no: int,
    specs: tuple[IndicatorSpec, ...] = INDICATOR_REGISTRY,
) -> list[Citation]:
    """Pull every unit-compatible number attributed to a registry indicator."""
    out: list[Citation] = []
    seen: set[tuple[str, float]] = set()
    for spec in specs:
        accepted = _ACCEPTED[spec.unit]
        for alias in spec.aliases:
            for m in _alias_pattern(alias).finditer(line):
                behind = line[max(0, m.start() - _FORECAST_LOOKBEHIND) : m.start()]
                # Qualifier guards apply both inside the alias gap ("유로존 근원
                # HICP") and just before it ("청년 유로존 실업률").
                context = (behind + m.group(0)).lower()
                if any(tok.lower() in context for tok in spec.reject_between):
                    continue
                if any(cue in behind.lower() for cue in _FORECAST_CUES):
                    continue
                window = line[m.end() : m.end() + CITE_WINDOW + _WINDOW_SLACK]
                if any(window.lstrip()[:8].startswith(t) for t in spec.reject_after):
                    continue  # "GDP 대비 100%" = 비율의 분모, 성장률 인용이 아님
                for cut in ("[", "\n", *spec.reject_between, *spec.reject_after):
                    idx = window.lower().find(cut.lower())
                    if idx >= 0:
                        window = window[:idx]
                numbers = _numbers_after(window, max_start=CITE_WINDOW)
                if not numbers or numbers[0][2] > FIRST_NUM_OFFSET:
                    continue
                if spec.unit == "level":
                    # Bare index/FX levels carry no unit signal, so only the
                    # number directly attached to the alias may be attributed
                    # ("…1.1696달러로 마감(…)하며 2주래 최저" must not yield 2).
                    numbers = [n for n in numbers if n[2] <= FIRST_NUM_OFFSET]
                for value, unit_class, _ in numbers:
                    if unit_class not in accepted:
                        continue
                    if (spec.key, value) in seen:
                        continue
                    seen.add((spec.key, value))
                    out.append(
                        Citation(
                            spec_key=spec.key,
                            line_no=line_no,
                            value=value,
                            unit_class=unit_class,
                            alias=alias,
                            snippet=(m.group(0) + window).strip()[:80],
                        )
                    )
    return out


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------


@dataclass
class NumericFinding:
    """One numeric review candidate. ``severity`` is priority, not verdict."""

    line_no: int
    indicator: str
    cited: float
    reference: float | None
    severity: str  # "high" | "info"
    note: str


_SEVERITY_ORDER = {"high": 0, "info": 1}


def _within_tolerance(
    spec: IndicatorSpec, cited: float, reference: float, tol_pct: float
) -> bool:
    if spec.tol_abs is not None:
        return abs(cited - reference) <= spec.tol_abs
    if reference == 0:
        return abs(cited) < 1e-9
    return abs(cited - reference) / abs(reference) * 100.0 <= tol_pct


def _lookup(
    spec: IndicatorSpec, as_of: date, sources: list[ReferenceSource]
) -> RefValue | None:
    attempts = [spec]
    if spec.fallback is not None:
        attempts.append(
            replace(spec, source_kind=spec.fallback[0], series_key=spec.fallback[1])
        )
    for attempt in attempts:
        for source in sources:
            if attempt.source_kind not in getattr(source, "handles", frozenset()):
                continue
            probe = getattr(source, "available", None)
            try:
                if probe is not None and not probe():
                    continue
                ref = source.lookup(attempt, as_of)
            except Exception:
                continue
            if ref is not None:
                return ref
    return None


def _fmt(value: float) -> str:
    return f"{value:g}"


def scan_numeric_issues(
    text: str,
    *,
    as_of: date,
    sources: list[ReferenceSource],
    tol_pct: float = 2.0,
    specs: tuple[IndicatorSpec, ...] = INDICATOR_REGISTRY,
) -> list[NumericFinding]:
    """Flag cited numbers that contradict (or cannot be checked against) our stores.

    severity:
      - ``"high"``: the value is outside the indicator's plausible range, or a
        reference exists and *no* number cited for that indicator agrees with
        it within tolerance → likely fabricated / mis-transcribed.
      - ``"info"``: the indicator is cited but no reference value is available
        (store gap, thin coverage, source unavailable) → unverifiable, not wrong.

    Advisory only — never raises, never gates a publish.
    """
    # Judgement is per (indicator, line): a report may cite an indicator
    # correctly in one paragraph and wrongly in another, so acquittal must
    # never leak across lines.
    citations: dict[tuple[str, int], list[Citation]] = {}
    line_values: dict[int, list[tuple[float, str]]] = {}
    for line_no, line in auditable_lines(text):
        cites = extract_citations(line, line_no, specs)
        if not cites:
            continue
        for cite in cites:
            citations.setdefault((cite.spec_key, cite.line_no), []).append(cite)
        line_values[line_no] = [(v, u) for v, u, _ in _numbers_after(line)]

    findings: list[NumericFinding] = []
    by_key = {s.key: s for s in specs}
    ref_cache: dict[str, RefValue | None] = {}
    reported_missing: set[str] = set()

    for (spec_key, line_no), cites in citations.items():
        spec = by_key[spec_key]
        plausible = [c for c in cites if spec.lo <= c.value <= spec.hi]

        for cite in cites:
            if cite in plausible:
                continue
            findings.append(
                NumericFinding(
                    line_no=cite.line_no,
                    indicator=spec.label,
                    cited=cite.value,
                    reference=None,
                    severity="high",
                    note=(
                        f"불가능 값 — 플로저빌리티 범위 [{_fmt(spec.lo)}, "
                        f"{_fmt(spec.hi)}]{spec.unit} 밖 · {cite.snippet}"
                    ),
                )
            )
        if not plausible:
            continue

        if spec_key not in ref_cache:
            ref_cache[spec_key] = _lookup(spec, as_of, sources)
        ref = ref_cache[spec_key]

        if ref is None:
            # One INFO per indicator, not per mention — the gap is the store's,
            # and repeating it per paragraph would bury the HIGH findings.
            if spec_key in reported_missing:
                continue
            reported_missing.add(spec_key)
            first = plausible[0]
            findings.append(
                NumericFinding(
                    line_no=first.line_no,
                    indicator=spec.label,
                    cited=first.value,
                    reference=None,
                    severity="info",
                    note=(
                        f"참조값 없음 — 대조 불가 ({spec.source_kind}:"
                        f"{spec.series_key}) · {spec.note}"
                    ),
                )
            )
            continue

        if any(_within_tolerance(spec, c.value, ref.value, tol_pct) for c in plausible):
            continue
        # Line-level acquittal: the correct figure sits elsewhere on the same
        # line ("2025년 8회 인하로 2.00% 저점 → 2026-06-11 첫 인상(2.25%)").
        accepted = _ACCEPTED[spec.unit]
        if any(
            unit_class in accepted
            and _within_tolerance(spec, value, ref.value, tol_pct)
            for value, unit_class in line_values.get(line_no, ())
        ):
            continue

        closest = min(plausible, key=lambda c: abs(c.value - ref.value))
        # An undated or stale reference cannot convict a fresh print.
        stale = ref.as_of is None or (as_of - ref.as_of).days > MAX_REF_AGE_DAYS
        cited_all = ", ".join(_fmt(c.value) for c in plausible)
        tol_desc = (
            f"±{_fmt(spec.tol_abs)}{spec.unit}"
            if spec.tol_abs is not None
            else f"±{_fmt(tol_pct)}%(상대)"
        )
        stale_note = (
            f" · ⚠ 참조 기준일 불명 또는 {MAX_REF_AGE_DAYS}일 이상 스테일 "
            "→ 대조 신뢰 불가(INFO 강등)"
            if stale
            else ""
        )
        findings.append(
            NumericFinding(
                line_no=closest.line_no,
                indicator=spec.label,
                cited=closest.value,
                reference=ref.value,
                severity="info" if stale else "high",
                note=(
                    f"인용 {{{cited_all}}} vs 참조 {_fmt(ref.value)}"
                    f"{f' ({ref.as_of})' if ref.as_of else ''} "
                    f"[{ref.source}:{ref.key}] · 허용오차 {tol_desc} 초과 "
                    f"(Δ{closest.value - ref.value:+.2f}){stale_note} · "
                    f"{closest.snippet}"
                ),
            )
        )

    findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.line_no))
    return findings


def render_report(findings: list[NumericFinding]) -> str:
    """Human-readable summary, HIGH first."""
    if not findings:
        return "수치 감사: 레지스트리 지표 인용에서 모순 없음 (clean)."

    counts = {
        sev: sum(1 for f in findings if f.severity == sev) for sev in _SEVERITY_ORDER
    }
    lines = [
        f"수치 감사: HIGH {counts['high']} / INFO {counts['info']}",
        "  (advisory — 발행 차단 없음. HIGH = 저장소 값과 모순되거나 불가능한 값,",
        "   INFO = 참조값 부재로 대조 불가. 정규식 추출이므로 오탐 가능.)",
        "",
    ]
    for f in findings:
        tag = "🔴" if f.severity == "high" else "ℹ️"
        ref = "참조 없음" if f.reference is None else f"참조 {_fmt(f.reference)}"
        lines.append(
            f"{tag} L{f.line_no} {f.indicator}: 인용 {_fmt(f.cited)} · {ref} — {f.note}"
        )
    return "\n".join(lines)
