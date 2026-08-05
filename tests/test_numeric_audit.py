"""Tests for the deterministic numeric audit (advisory)."""

from __future__ import annotations

from datetime import date

import pytest

from indepth_analysis.numeric_audit import (
    INDICATOR_REGISTRY,
    IndicatorSpec,
    MacroStoreSource,
    NumericFinding,
    OptionsdeckSource,
    RefValue,
    _validate_registry,
    auditable_lines,
    build_default_sources,
    extract_citations,
    render_report,
    scan_numeric_issues,
)

AS_OF = date(2026, 6, 30)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class FakeSource:
    """A ReferenceSource returning canned values keyed by spec key."""

    name = "fake"
    handles = frozenset({"rate", "fx", "calendar", "series"})

    def __init__(
        self,
        values: dict[str, RefValue] | None = None,
        *,
        is_available: bool = True,
    ) -> None:
        self._values = values or {}
        self._available = is_available
        self.lookups: list[str] = []

    def available(self) -> bool:
        return self._available

    def lookup(self, spec: IndicatorSpec, as_of: date) -> RefValue | None:
        self.lookups.append(spec.key)
        return self._values.get(spec.key)


def ref(value: float, *, days_old: int = 5) -> RefValue:
    return RefValue(
        value=value,
        as_of=AS_OF.fromordinal(AS_OF.toordinal() - days_old),
        source="fake",
        key="k",
    )


def scan(text: str, sources, **kw) -> list[NumericFinding]:
    return scan_numeric_issues(text, as_of=AS_OF, sources=sources, **kw)


# --------------------------------------------------------------------------
# registry policy
# --------------------------------------------------------------------------


def test_registry_has_no_policy_violations() -> None:
    """Every alias carries a country/region qualifier; keys/units are valid."""
    assert _validate_registry(INDICATOR_REGISTRY) == []


def test_registry_specs_declare_their_reference_key() -> None:
    for spec in INDICATOR_REGISTRY:
        assert spec.source_kind in {"rate", "fx", "calendar", "series"}
        assert spec.series_key
        assert spec.lo < spec.hi


# --------------------------------------------------------------------------
# matching / verdicts
# --------------------------------------------------------------------------


def test_matching_citation_produces_no_finding() -> None:
    text = "4월 유로존 실업률은 6.3%로 전월과 동일한 수준을 유지했다."
    src = FakeSource({"ea_unemployment": ref(6.3)})
    assert scan(text, [src]) == []


def test_deviation_beyond_tolerance_is_high() -> None:
    text = "4월 유로존 실업률은 5.1%로 급락했다."
    src = FakeSource({"ea_unemployment": ref(6.3)})
    findings = scan(text, [src])
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert findings[0].cited == 5.1
    assert findings[0].reference == 6.3
    assert "유로존 실업률" in findings[0].indicator


def test_missing_reference_is_info_not_high() -> None:
    text = "4월 유로존 실업률은 5.1%였다."
    findings = scan(text, [FakeSource({})])
    assert [f.severity for f in findings] == ["info"]
    assert findings[0].reference is None
    assert "참조값 없음" in findings[0].note


def test_implausible_value_is_high_without_any_reference() -> None:
    """Out-of-range values are impossible regardless of store coverage."""
    text = "유로존 실업률이 63.0%까지 치솟았다."
    findings = scan(text, [FakeSource({})])
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert findings[0].cited == 63.0
    assert "불가능 값" in findings[0].note


def test_transition_phrasing_is_acquitted() -> None:
    """'2.00%에서 2.25%로' must not be read as a 2.00% claim."""
    text = "ECB는 예금금리(DFR)를 2.00%에서 2.25%로 인상했다."
    src = FakeSource({"ecb_dfr": ref(2.25)})
    assert scan(text, [src]) == []


def test_acquittal_does_not_leak_across_lines() -> None:
    """A correct mention elsewhere must not excuse a wrong one."""
    text = (
        "ECB 예금금리는 2.25%로 인상됐다.\n"
        "\n"
        "한편 ECB 예금금리는 1.25%로 유지되고 있다.\n"
    )
    src = FakeSource({"ecb_dfr": ref(2.25)})
    findings = scan(text, [src])
    assert [(f.severity, f.cited) for f in findings] == [("high", 1.25)]
    assert findings[0].line_no == 3


def test_stale_reference_downgrades_to_info() -> None:
    text = "유로존 HICP는 3.2%로 가속했다."
    src = FakeSource({"ea_hicp": ref(1.9, days_old=400)})
    findings = scan(text, [src])
    assert [f.severity for f in findings] == ["info"]
    assert "스테일" in findings[0].note


# --------------------------------------------------------------------------
# extraction guards
# --------------------------------------------------------------------------


def test_bare_indicator_word_is_ignored() -> None:
    """A country-less '실업률' must never be attributed to the euro area."""
    text = "실업률은 5.1%로 하락했고, 청년 실업률은 14.7%였다."
    src = FakeSource({"ea_unemployment": ref(6.3)})
    assert scan(text, [src]) == []
    assert extract_citations(text, 1) == []


def test_country_qualifier_prefix_blocks_misattribution() -> None:
    """'청년 유로존 실업률' is a different series than '유로존 실업률'."""
    assert extract_citations("청년 유로존 실업률은 14.7%다.", 1) == []


def test_core_and_headline_hicp_do_not_cross_contaminate() -> None:
    cites = extract_citations("유로존 HICP는 3.2%, 유로존 근원 HICP는 2.5%다.", 1)
    values = {(c.spec_key, c.value) for c in cites}
    assert ("ea_hicp", 3.2) in values
    assert ("ea_hicp_core", 2.5) in values
    assert ("ea_hicp", 2.5) not in values


def test_magnitude_expressions_are_ignored() -> None:
    """'조/억/만' magnitudes are not indicator levels."""
    text = "유로존 실업률 통계상 실업자는 1,107.5만 명, 재정적자는 1.2조 유로다."
    assert extract_citations(text, 1) == []


def test_range_expression_is_ignored() -> None:
    text = "유로존 HICP는 1.5~2.0% 범위에 머물 것이다."
    src = FakeSource({"ea_hicp": ref(3.2)})
    assert scan(text, [src]) == []


def test_percentage_point_change_is_not_read_as_a_level() -> None:
    """%p denotes a change; only % denotes the level a spec compares."""
    pp_only = extract_citations("독일 GDP는 0.3%p 상향 조정됐다.", 1)
    assert pp_only == []
    level = extract_citations("독일 GDP는 전기비 +0.3%를 기록했다.", 1)
    assert [(c.spec_key, c.value, c.unit_class) for c in level] == [
        ("de_gdp_qoq", 0.3, "pct")
    ]


def test_basis_point_move_is_not_read_as_a_policy_rate_level() -> None:
    text = "ECB 정책금리를 25bp 인상했다."
    assert extract_citations(text, 1) == []


def test_share_of_gdp_idiom_is_not_a_growth_citation() -> None:
    text = (
        "프랑스 GDP 대비 공공부채는 115.8%이며, 유로존 GDP의 70%를 서비스가 차지한다."
    )
    assert extract_citations(text, 1) == []


def test_forecast_context_is_skipped() -> None:
    text = "ECB 전망은 유로존 HICP를 2027년 2.3%로 제시했다."
    src = FakeSource({"ea_hicp": ref(3.2)})
    assert scan(text, [src]) == []


def test_date_like_tokens_are_not_fx_levels() -> None:
    text = "EUR/USD 1.1796(4/14) 기준으로 디커플링이 반영됐다."
    cites = extract_citations(text, 1)
    assert [c.value for c in cites] == [1.1796]


# --------------------------------------------------------------------------
# scoping
# --------------------------------------------------------------------------


DETERMINISTIC_REPORT = """# 2026년 6월 월간 유럽 거시경제 현황

## 목차

- 유로존 실업률 99.0%

## 3. 물가 및 인플레이션

유로존 HICP는 3.2%로 가속했다.

## B. ForexFactory 주요 지표 서프라이즈 (최근 30일)

유로존 실업률 99.0% 서프라이즈

## G. FX 환율 스냅샷 (EUR 기준)

| 통화 | 환율 |
| --- | --- |
| USD | 99.0 |

## 부록 I. 언론 보도 및 1차 출처 요약 (2026년 6월)

유로존 실업률 99.0% 보도

## 부록 II. 주요국별 심층 분석 (2026년 6월)

독일 GDP는 전기비 +0.3%를 기록했다.

## 부록 IV. 출처 목록

유로존 실업률 99.0%

## 참고문헌

유로존 실업률 99.0%
"""


def test_deterministic_sections_are_skipped() -> None:
    """Sections rendered from the same stores are not re-checked (circular)."""
    audited = " ".join(line for _, line in auditable_lines(DETERMINISTIC_REPORT))
    assert "99.0%" not in audited
    assert "유로존 HICP는 3.2%" in audited
    assert "독일 GDP는 전기비 +0.3%" in audited  # 부록 II = LLM 산문 → 감사 대상


def test_deterministic_sections_produce_no_findings() -> None:
    findings = scan(DETERMINISTIC_REPORT, [FakeSource({})])
    assert all(f.cited != 99.0 for f in findings)


def test_markdown_tables_and_code_fences_are_skipped() -> None:
    text = "| 유로존 실업률 | 99.0% |\n```\n유로존 실업률 99.0%\n```\n"
    assert auditable_lines(text) == []


# --------------------------------------------------------------------------
# sources
# --------------------------------------------------------------------------


def test_unavailable_source_is_bypassed_without_error() -> None:
    """An unavailable source must be skipped, not crash or convict."""
    dead = FakeSource({"ea_unemployment": ref(6.3)}, is_available=False)
    findings = scan("유로존 실업률은 5.1%였다.", [dead])
    assert dead.lookups == []
    assert [f.severity for f in findings] == ["info"]


def test_raising_source_is_bypassed() -> None:
    class Exploding:
        name = "boom"
        handles = frozenset({"calendar"})

        def available(self) -> bool:
            return True

        def lookup(self, spec, as_of):
            raise RuntimeError("db gone")

    findings = scan("유로존 실업률은 5.1%였다.", [Exploding()])
    assert [f.severity for f in findings] == ["info"]


def test_optionsdeck_source_is_optional_and_duck_typed() -> None:
    """T1's adapter may not exist yet; absence must degrade silently."""

    class StrictArityClient:
        """Only accepts the 3-positional-arg form → exercises the fallback."""

        def available(self) -> bool:
            return True

        def get_series(self, series_id, start, end):
            return [("2026-06-01", 3.2), {"date": "2026-06-15", "value": 3.4}]

    class ObservationLikeClient:
        """Mirrors T1's adapter: 1-arg call, objects with heterogeneous labels."""

        def available(self) -> bool:
            return True

        def get_series(self, series_id, start=None, end=None):
            class Obs:
                def __init__(self, d, v):
                    self.date, self.value = d, v

            return [Obs("2026-05", 3.0), Obs("2026-Q2", 3.4), Obs("2026-12", 9.9)]

    spec = next(s for s in INDICATOR_REGISTRY if s.key == "ea_hicp")

    src = OptionsdeckSource(StrictArityClient())
    assert src.available() is True
    got = src.lookup(spec, AS_OF)
    assert got is not None
    assert got.value == 3.4
    assert got.as_of == date(2026, 6, 15)

    # quarter/month labels resolve, and observations after as-of are excluded
    got2 = OptionsdeckSource(ObservationLikeClient()).lookup(spec, AS_OF)
    assert got2 is not None
    assert got2.value == 3.4
    assert got2.as_of == date(2026, 6, 30)


def test_optionsdeck_source_unavailable_client_is_dropped() -> None:
    class Broken:
        def available(self) -> bool:
            return False

        def get_series(self, series_id, start, end):  # pragma: no cover
            raise AssertionError("must not be called")

    src = OptionsdeckSource(Broken())
    assert src.available() is False
    findings = scan("유로존 실업률은 5.1%였다.", [src])
    assert [f.severity for f in findings] == ["info"]


def test_macro_store_source_reads_rates_fx_and_calendar(tmp_db) -> None:
    from datetime import UTC, datetime

    from bgilib.macro.models import CalendarEvent, FXRate, RateDecision
    from bgilib.macro.storage import MacroStore

    store = MacroStore(tmp_db)
    store.upsert_rate(
        RateDecision(
            country="EUR",
            cb_name="ECB",
            date_utc=date(2026, 6, 11),
            rate_pct=2.25,
            prev_rate=2.00,
            change_bp=25,
            source="test",
        )
    )
    store.upsert_fx_rate(
        FXRate(
            date_utc=date(2026, 6, 29),
            base="EUR",
            quote="USD",
            rate=1.1515,
            source="test",
        )
    )
    for title, actual in (
        ("CPI Flash Estimate y/y", 3.2),
        ("Core CPI Flash Estimate y/y", 2.5),
    ):
        store.upsert_event(
            CalendarEvent(
                event_id=f"e-{title}",
                country="EUR",
                title=title,
                impact="High",
                datetime_utc=datetime(2026, 6, 2, 9, 0, tzinfo=UTC),
                forecast=3.0,
                actual=actual,
                is_released=True,
            )
        )

    src = MacroStoreSource(store)
    assert src.available() is True
    by_key = {s.key: s for s in INDICATOR_REGISTRY}

    rate = src.lookup(by_key["ecb_dfr"], AS_OF)
    assert rate is not None and rate.value == 2.25

    fx = src.lookup(by_key["eurusd"], AS_OF)
    assert fx is not None and fx.value == pytest.approx(1.1515)

    # exact-title match: the Core row must not answer for the headline spec
    headline = src.lookup(by_key["ea_hicp"], AS_OF)
    core = src.lookup(by_key["ea_hicp_core"], AS_OF)
    assert headline is not None and headline.value == 3.2
    assert core is not None and core.value == 2.5

    # nothing stored for unemployment → honest None, not a wrong answer
    assert src.lookup(by_key["ea_unemployment"], AS_OF) is None


def test_macro_store_source_missing_db_is_unavailable(tmp_path) -> None:
    src = MacroStoreSource(db_path=tmp_path / "nope.db")
    assert src.available() is False
    spec = next(s for s in INDICATOR_REGISTRY if s.key == "ecb_dfr")
    assert src.lookup(spec, AS_OF) is None


def test_build_default_sources_never_raises(tmp_path) -> None:
    sources = build_default_sources(db_path=tmp_path / "absent.db")
    assert all(hasattr(s, "lookup") for s in sources)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def test_render_report_clean() -> None:
    assert "clean" in render_report([])


def test_render_report_lists_high_first_and_states_advisory() -> None:
    text = (
        "유로존 실업률은 5.1%였다.\n"
        "\n"
        "ECB 예금금리는 2.25%로 인상됐다.\n"
        "\n"
        "유로존 HICP는 9.9%로 급등했다.\n"
    )
    src = FakeSource({"ea_hicp": ref(3.2), "ecb_dfr": ref(2.25)})
    findings = scan(text, [src])
    out = render_report(findings)
    assert "HIGH 1 / INFO 1" in out
    assert "advisory" in out
    assert out.index("🔴") < out.index("ℹ️")
    assert "L5" in out


def test_scan_is_advisory_and_never_raises_on_garbage() -> None:
    for junk in ("", "\n\n", "%%%", "유로존 실업률은 %다.", "## \n| |"):
        assert scan(junk, [FakeSource({})]) == []


def test_tol_pct_is_configurable_for_level_indicators() -> None:
    text = "EUR/USD는 1.20달러 수준이다."
    src = FakeSource({"eurusd": ref(1.1515)})
    assert scan(text, [src], tol_pct=2.0)  # 4.2% 괴리 → HIGH
    assert scan(text, [src], tol_pct=10.0) == []
