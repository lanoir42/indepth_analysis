"""Tests for the masterclass Stage 1 context pack builder (deterministic layer)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from bgilib.macro.models import CalendarEvent, RateDecision
from bgilib.macro.storage import MacroStore

from indepth_analysis.skills.euro_macro.masterclass.context_pack import (
    BackboneTable,
    build_backbone_tables,
    build_context_pack,
    build_deltas,
    default_context_path,
    extract_inline_sources,
    extract_numeric_sentences,
    load_context_pack,
    parse_report_markdown,
    render_markdown_table,
    save_context_pack,
    score_topic_candidates,
)

CURRENT_REPORT = """# 2026년 8월 월간 유럽 거시경제 현황

## 목차
- [1. 통화정책 및 금리 동향](#1)

## 1. 통화정책 및 금리 동향

ECB 정책위원회는 예금금리를 25bp 인상해 2.25%로 결정했다 [출처: ECB, 2026-06-11].
시장은 9월 회의 인상 확률을 약 70%로 반영했다 [출처: CNBC, 2026-07-23].
짧은 문장.

## 2. 물가 및 인플레이션

7월 유로존 HICP는 2.9%로 6월(2.8%) 대비 상승했다 [출처: Eurostat, 2026-07-31].
에너지 물가 상승률은 10.0%로 헤드라인 상승을 주도했다 [출처: Eurostat, 2026-07-31].

## A. ForexFactory 향후 거시 캘린더 (다음 14일)

| 일시 | 국가 | 지표 |
|---|---|---|
| 08-07 | 미국 | Non-Farm Employment Change |

## 부록 III. 리스크 시나리오 분석 (2026년 8월)

# 2026년 8월 유럽 경제 리스크 시나리오 분석

## 1. 기준 시나리오 (Base Case)

성장률 0.4%, 확률 55%로 본다.

## 종합 및 판단 (자료 기반)

에너지 리스크가 관건이다.

## 부록 V. 유럽 정치지형 심층 분석 (2026년 8월)

프랑스 국민연합(RN)이 여론조사 1위를 유지했다.

## 참고문헌

- 출처: https://www.ecb.europa.eu/press/pr/date/2026/example.html

## 참고 자료

### KCIF
- 유럽 월간 보고서
"""

PREVIOUS_REPORT = """# 2026년 7월 월간 유럽 거시경제 현황

## 1. 통화정책 및 금리 동향

ECB는 7월 회의에서 예금금리 2.25%를 동결했다 [출처: ECB, 2026-07-23].

## 2. 물가 및 인플레이션

6월 유로존 HICP는 2.8%를 기록했다 [출처: Eurostat, 2026-07-01].

## 3. 사라질 섹션

이 섹션은 8월에 없다. 값은 1.5% 수준이었다.
"""

DIFFERENT_FORMAT_REPORT = """# 유럽 매크로 월간 업데이트 — 2026년 7월

## 1. 핵심 요약

하반기 성장은 연율 0.5~1.0%에 머문다.

## 2. 6월 주요 이벤트 회고

ECB가 6월 11일 25bp 인상했다.
"""


def _write_reports(tmp_path: Path, *, previous: str | None = PREVIOUS_REPORT) -> Path:
    reports = tmp_path / "reports" / "euro_macro"
    reports.mkdir(parents=True)
    (reports / "2026-08.md").write_text(CURRENT_REPORT, encoding="utf-8")
    if previous is not None:
        (reports / "2026-07.md").write_text(previous, encoding="utf-8")
    return reports


# --- 리포트 파싱 -------------------------------------------------------------


def test_parse_report_splits_top_level_sections_only() -> None:
    title, sections = parse_report_markdown(CURRENT_REPORT)
    assert title == "2026년 8월 월간 유럽 거시경제 현황"
    keys = [s.key for s in sections]
    assert keys == ["목차", "1", "2", "A", "부록 III", "부록 V", "참고 자료"]
    kinds = {s.key: s.kind for s in sections}
    assert kinds["1"] == "body"
    assert kinds["A"] == "deterministic"
    assert kinds["부록 III"] == "appendix"
    assert kinds["참고 자료"] == "meta"


def test_appendix_internal_headings_stay_nested() -> None:
    """부록 III의 ``## 1. 기준 시나리오``는 본문 1장으로 승격되면 안 된다."""
    _, sections = parse_report_markdown(CURRENT_REPORT)
    appendix = next(s for s in sections if s.key == "부록 III")
    assert "기준 시나리오" in appendix.text
    assert "성장률 0.4%, 확률 55%로 본다." in appendix.text
    assert "1. 기준 시나리오 (Base Case)" in appendix.subheadings
    # 부록 V 내부의 '## 참고문헌'도 최상위 메타 섹션이 되면 안 된다.
    appendix_v = next(s for s in sections if s.key == "부록 V")
    assert "참고문헌" in appendix_v.subheadings
    assert "ecb.europa.eu" in appendix_v.text


def test_numeric_sentence_and_source_extraction() -> None:
    _, sections = parse_report_markdown(CURRENT_REPORT)
    sec = next(s for s in sections if s.key == "1")
    assert len(sec.numeric_sentences) == 2
    assert all("%" in s or "bp" in s for s in sec.numeric_sentences)
    assert "짧은 문장." not in sec.numeric_sentences
    assert sec.inline_sources == ["ECB, 2026-06-11", "CNBC, 2026-07-23"]

    v = next(s for s in sections if s.key == "부록 V")
    assert v.source_urls == [
        "https://www.ecb.europa.eu/press/pr/date/2026/example.html"
    ]


def test_extract_helpers_are_standalone() -> None:
    text = "HICP는 2.9%로 상승했다 [출처: Eurostat, 2026-07-31; ECB, 2026-06-11]."
    assert extract_numeric_sentences(text) == [text]
    assert extract_inline_sources(text) == ["Eurostat, 2026-07-31", "ECB, 2026-06-11"]
    assert extract_numeric_sentences("| 표 | 행 | 2.9% |") == []


# --- 전월 델타 ---------------------------------------------------------------


def test_build_deltas_pairs_matching_sections() -> None:
    _, current = parse_report_markdown(CURRENT_REPORT)
    _, previous = parse_report_markdown(PREVIOUS_REPORT)
    deltas = build_deltas(current, previous)
    by_key = {d.key: d for d in deltas}

    assert by_key["1"].match_kind == "heading"
    assert "동결" in by_key["1"].prev_gist
    assert "인상" in by_key["1"].curr_gist
    assert by_key["1"].prev_numbers and by_key["1"].curr_numbers
    assert by_key["A"].match_kind == "new"
    assert by_key["3"].match_kind == "dropped"
    assert by_key["3"].prev_heading == "3. 사라질 섹션"
    assert all(d.key != "목차" for d in deltas)  # 메타 섹션은 델타 대상 아님


def test_build_deltas_empty_without_previous_month() -> None:
    _, current = parse_report_markdown(CURRENT_REPORT)
    assert build_deltas(current, []) == []


def test_build_deltas_does_not_pair_dissimilar_headings() -> None:
    """포맷이 바뀐 달은 키가 같아도 짝짓지 않는다 (엉뚱한 서사 변화 방지)."""
    _, current = parse_report_markdown(CURRENT_REPORT)
    _, previous = parse_report_markdown(DIFFERENT_FORMAT_REPORT)
    deltas = build_deltas(current, previous)
    by_key = {(d.key, d.match_kind) for d in deltas}
    assert ("1", "new") in by_key
    assert ("1", "dropped") in by_key
    assert not any(d.match_kind in {"heading", "key"} for d in deltas)


# --- 주제 스코어링 -----------------------------------------------------------


def test_score_topic_candidates_ranks_report_events() -> None:
    _, sections = parse_report_markdown(CURRENT_REPORT)
    candidates = score_topic_candidates(sections)
    ids = [c.topic_id for c in candidates]
    assert "ecb-policy-mechanics" in ids
    assert "hicp-anatomy" in ids
    assert "france-institutions" in ids
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)
    top = candidates[0]
    assert top.score > 0
    assert top.keyword_hits
    assert top.evidence
    assert top.sections


def test_score_topic_candidates_ignores_meta_sections() -> None:
    _, sections = parse_report_markdown(CURRENT_REPORT)
    candidates = score_topic_candidates(sections)
    for cand in candidates:
        assert "목차" not in cand.sections
        assert "참고 자료" not in cand.sections


# --- 백본 표 -----------------------------------------------------------------


def _seed_store(path: Path) -> MacroStore:
    store = MacroStore(path)
    # HICP 골든 체인 (flash/final)
    for i, (day, actual, forecast) in enumerate(
        [
            ("2026-06-02", 3.2, 3.1),
            ("2026-07-01", 2.8, 3.0),
            ("2026-07-31", 2.9, 2.8),
        ]
    ):
        store.upsert_event(
            CalendarEvent(
                event_id=f"flash-{i}",
                country="EUR",
                title="CPI Flash Estimate y/y",
                impact="High",
                datetime_utc=datetime.fromisoformat(day).replace(tzinfo=UTC),
                forecast=forecast,
                previous=None,
                actual=actual,
                is_released=True,
                source="golden:eurostat",
            )
        )
    store.upsert_event(
        CalendarEvent(
            event_id="final-0",
            country="EUR",
            title="Final CPI y/y",
            impact="High",
            datetime_utc=datetime(2026, 7, 17, tzinfo=UTC),
            actual=2.8,
            is_released=True,
            source="golden:eurostat",
        )
    )
    # 미래(당월 이후) 이벤트는 표에 들어오면 안 된다.
    store.upsert_event(
        CalendarEvent(
            event_id="flash-future",
            country="EUR",
            title="CPI Flash Estimate y/y",
            impact="High",
            datetime_utc=datetime(2026, 9, 1, tzinfo=UTC),
            actual=3.5,
            is_released=True,
            source="golden:eurostat",
        )
    )
    # 서프라이즈 통계용 표본 (n >= 6)
    for i in range(8):
        store.upsert_event(
            CalendarEvent(
                event_id=f"us-nfp-{i}",
                country="USD",
                title="Non-Farm Employment Change",
                impact="High",
                datetime_utc=datetime(2026, 1, 5, tzinfo=UTC)
                + timedelta(days=30 * i),
                forecast=100.0,
                actual=100.0 + i,
                is_released=True,
            )
        )
    # 정책금리
    store.upsert_rate(
        RateDecision(
            country="EUR",
            cb_name="ECB",
            date_utc=date(2026, 6, 11),
            rate_pct=2.25,
            prev_rate=2.00,
            change_bp=25,
        )
    )
    store.upsert_rate(
        RateDecision(
            country="USD",
            cb_name="Fed",
            date_utc=date(2026, 7, 1),
            rate_pct=3.63,
        )
    )
    return store


class _Obs:
    def __init__(self, day: str, value: float) -> None:
        self.date = day
        self.value = value


class _StubOptionsdeck:
    """Duck-typed stand-in for OptionsdeckSeriesClient (어댑터 경유 계약 유지)."""

    def __init__(self, series: dict[str, list[tuple[str, float]]], ok: bool = True):
        self._series = series
        self._ok = ok
        self.requested: list[str] = []

    def available(self) -> bool:
        return self._ok

    def get_series(self, series_id: str) -> list[_Obs]:
        self.requested.append(series_id)
        return [_Obs(d, v) for d, v in self._series.get(series_id, [])]


def _stub_client(ok: bool = True) -> _StubOptionsdeck:
    return _StubOptionsdeck(
        {
            "M.RCH_A.CP00.EA": [
                ("1997-01", 1.8),
                ("2022-10", 10.6),
                ("2026-06", 2.8),
                ("2026-07", 2.9),
                ("2026-12", 9.9),  # 당월 이후 — 잘려야 한다
            ],
            "VIXCLS": [
                ("2026-07-30", 18.0),
                ("2026-07-31", 18.2),
                ("2026-08-04", 15.5),
            ],
            "DCOILBRENTEU": [("2026-07-31", 91.8), ("2026-08-04", 79.5)],
        },
        ok=ok,
    )


def test_backbone_tables_from_local_db(tmp_path: Path) -> None:
    db = tmp_path / "macro.db"
    _seed_store(db)
    notes: list[str] = []
    client = _stub_client()
    tables = build_backbone_tables(
        2026, 8, db_path=db, optionsdeck_client=client, notes=notes
    )
    by_id = {t.id: t for t in tables}
    assert set(by_id) == {
        "hicp_golden_chain",
        "policy_rate_24m",
        "surprise_stats",
        "ea_hicp_long",
        "vix_brent_24m",
    }
    assert notes == []

    hicp = by_id["hicp_golden_chain"]
    assert len(hicp.rows) == 4  # 미래 발표 제외
    assert hicp.rows[0]["발표일"] == "2026-06-02"
    assert hicp.rows[0]["실제"] == "3.2%"
    assert hicp.rows[1]["서프라이즈"] == "-0.2%p"  # 2.8 - 3.0
    assert hicp.markdown.startswith("| 발표일 |")
    assert hicp.markdown.count("\n") == len(hicp.rows) + 1

    rates = by_id["policy_rate_24m"]
    assert len(rates.rows) == 24
    assert rates.rows[-1]["기준월"] == "2026-08"
    assert rates.rows[-1]["유로존(ECB)"] == "2.25%"  # carry-forward
    assert rates.rows[0]["유로존(ECB)"] is None  # 관측 이전 구간은 공백

    surprise = by_id["surprise_stats"]
    assert surprise.rows[0]["지표"] == "Non-Farm Employment Change"
    assert surprise.rows[0]["표본수"] >= 6

    ea = by_id["ea_hicp_long"]
    assert [r["기준월"] for r in ea.rows] == [
        "1997-01",
        "2022-10",
        "2026-06",
        "2026-07",
    ]
    assert "10.6%" in ea.note and "백분위" in ea.note

    vix = by_id["vix_brent_24m"]
    assert len(vix.rows) == 24
    assert vix.rows[-2]["VIX (월말)"] == "18.20"  # 2026-07 월말 관측치
    assert vix.rows[-1]["Brent $/bbl (월말)"] == "79.50"
    assert client.requested  # 어댑터를 경유했음


def test_backbone_tables_degrade_gracefully_without_sources(tmp_path: Path) -> None:
    notes: list[str] = []
    tables = build_backbone_tables(
        2026,
        8,
        db_path=tmp_path / "missing.db",
        optionsdeck_client=_stub_client(ok=False),
        notes=notes,
    )
    assert tables == []
    assert any("매크로 캘린더 DB 없음" in n for n in notes)
    assert any("optionsdeck" in n for n in notes)


def test_empty_backbone_table_is_dropped_with_note(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    MacroStore(db)  # 스키마만 있는 빈 DB
    notes: list[str] = []
    tables = build_backbone_tables(
        2026, 8, db_path=db, optionsdeck_client=_StubOptionsdeck({}), notes=notes
    )
    ids = {t.id for t in tables}
    assert "hicp_golden_chain" not in ids  # 행이 없으면 제외
    assert "policy_rate_24m" in ids  # 월 라벨은 남으므로 유지
    assert any("hicp_golden_chain" in n for n in notes)


def test_render_markdown_table_handles_none_and_empty() -> None:
    assert render_markdown_table(["a", "b"], []) == ""
    md = render_markdown_table(["a", "b"], [{"a": 1, "b": None}])
    assert md.splitlines() == ["| a | b |", "|---|---|", "| 1 |  |"]
    assert BackboneTable(id="x", title="t").is_empty


# --- 조립 / 직렬화 -----------------------------------------------------------


def test_build_context_pack_end_to_end(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path)
    db = tmp_path / "macro.db"
    _seed_store(db)
    pack = build_context_pack(
        2026,
        8,
        reports_dir=reports,
        db_path=db,
        optionsdeck_client=_stub_client(),
    )
    assert pack.year == 2026 and pack.month == 8
    assert pack.report_title.startswith("2026년 8월")
    assert pack.has_prev_month is True
    assert (pack.prev_year, pack.prev_month) == (2026, 7)
    assert [s.key for s in pack.sections][:3] == ["목차", "1", "2"]
    assert pack.section("1") is not None
    assert pack.headline_numbers  # 본문 수치 문장
    assert "ECB, 2026-06-11" in pack.inline_sources
    assert pack.source_urls
    assert {d.match_kind for d in pack.deltas} >= {"heading", "new", "dropped"}
    assert pack.table("policy_rate_24m") is not None
    assert all(t.markdown and t.rows for t in pack.backbone_tables)
    assert pack.topic_candidates
    assert pack.generated_at


def test_build_context_pack_without_previous_month(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, previous=None)
    pack = build_context_pack(
        2026,
        8,
        reports_dir=reports,
        db_path=tmp_path / "missing.db",
        optionsdeck_client=_stub_client(ok=False),
    )
    assert pack.has_prev_month is False
    assert pack.deltas == []
    assert pack.prev_report_path is None
    assert any("전월 리포트 없음" in n for n in pack.notes)
    assert pack.backbone_tables == []
    assert pack.sections  # 리포트 파싱은 정상


def test_build_context_pack_missing_report_raises(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        build_context_pack(2026, 8, reports_dir=tmp_path / "empty")


def test_context_pack_json_roundtrip(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path)
    db = tmp_path / "macro.db"
    _seed_store(db)
    pack = build_context_pack(
        2026, 8, reports_dir=reports, db_path=db, optionsdeck_client=_stub_client()
    )
    path = save_context_pack(pack, reports_dir=reports)
    assert path == default_context_path(2026, 8, reports_dir=reports)
    assert path.name == "2026-08-context.json"
    assert path.parent.name == "masterclass"

    loaded = load_context_pack(path)
    assert loaded.model_dump() == pack.model_dump()
    assert loaded.table("hicp_golden_chain").markdown == (
        pack.table("hicp_golden_chain").markdown
    )
    assert "ECB" in path.read_text(encoding="utf-8")


def test_save_context_pack_honours_explicit_path(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path)
    pack = build_context_pack(
        2026,
        8,
        reports_dir=reports,
        db_path=tmp_path / "missing.db",
        optionsdeck_client=_stub_client(ok=False),
    )
    target = tmp_path / "custom" / "pack.json"
    assert save_context_pack(pack, target) == target
    assert load_context_pack(target).year == 2026
