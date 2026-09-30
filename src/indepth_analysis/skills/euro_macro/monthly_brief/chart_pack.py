"""차트 팩 생성기 — ``ROOT/data/chart_pack.json`` + ``ROOT/data/charts/<id>.csv``.

    M=indepth_analysis.skills.euro_macro.monthly_brief.chart_pack
    uv run python -m $M build --root reports/euro_macro/monthly_brief/2026-09
    # build는 표 팩(table_pack)·사실 블록(facts)도 함께 생성한다(--charts-only로 생략)

입력은 ``ROOT/data/series_store.json``(``datastore.store``) 하나뿐이다. 수치는 모두
코드가 저장소에서 산출하며 LLM은 관여하지 않는다.

정본 스키마 (chart_pack.json)
============================

최상위::

    {"version": "3.0.0", "as_of": "YYYY-MM-DD", "month": "YYYY-MM",
     "generated_at": ISO8601, "store_generated_at": ISO8601,
     "charts": [Chart, ...], "skipped": [{"id", "reason"}]}

Chart::

    {"id": str,                     # 파일명과 동일, CSV = data/charts/<id>.csv
     "section": str,                # monetary|inflation|growth|labour|markets|credit|
                                    # fiscal|energy|fx  (리포트 장 키)
     "order": int,                  # 장 내 배치 순서
     "kind": str,                   # line|bar|stacked_bar|step|dual_axis_line|table_ref
     "headline": bool,              # 요약·핵심 장표 후보(llm_web 사용 시 검증 WARN)
     "title": str,                  # 한국어. 수치는 데이터 값만 (CSV와 문자열 일치)
     "subtitle": str,               # 동일 규칙
     "x": {"type": "month|quarter|year|day|category", "from": str, "to": str,
           "labels": [str, ...]},   # 격자 전체. 결측 라벨을 절대 빼지 않는다
     "y": [{"id": "left|right", "label": str, "unit": str, "decimals": int,
            "min": float|null, "max": float|null}],
     "series": [{"key": str,        # series_store id (변환 시 동일 id 유지)
                 "name_ko": str, "axis": "left|right",
                 "mark": "line|bar|step",      # stacked_bar의 겹선 표시용
                 "color_role": "primary|secondary|accent|neutral|negative",
                 "gap": "break",               # 결측은 선을 끊는다(연결·보간 금지)
                 "freq": "D|M|Q|A|C",          # 변환 후 주기 (차트 x.type과 일치)
                 "transform": null|"monthly_avg"|"rebase100"|"return_pct",
                 "tier": "api|local_db|market|llm_web",
                 "source": str, "dataset": str, "url": str,
                 "decimals": int,              # 저장소 계열 고유 자릿수(보조)
                 "last_period": str|null,      # 격자 안 마지막 비결측 기간
                 "values": [float|null, ...],  # x.labels와 같은 길이
                 "status": [str|null, ...]}],  # final|flash|prelim|spot|estimate|null
     "reference_lines": [{"axis": "left", "y": float, "label": str}],
     "annotations": [{"x": str, "series": str|null, "label": str,
                      "kind": "flash|decision|note"}],
     "footnote": "자료: <기관(데이터셋)>, … · 기준일 YYYY-MM-DD[ · 주석]",
     "data_csv": "data/charts/<id>.csv",
     "as_of": "YYYY-MM-DD"}

CSV (long, UTF-8, 헤더 고정)::

    date,series_key,value,status,tier,source

- 격자 × 계열 전 조합을 싣는다. 결측은 ``value``·``status`` 공란.
- ``value``는 저장소 원값(반올림 전). 표시 자릿수는 y축 ``decimals``.

규칙
- 한 차트 = 한 주기. 일별과 월평균을 한 축에 섞지 않는다(월평균 변형은 별도 차트).
- 정책금리는 ECB FM 일별 적용 수준(발효일 기준). 결정일은 ``annotations``
  (kind=decision)에 ``결정 YYYY-MM-DD · 발효 YYYY-MM-DD``로만 표기한다.
- 월평균(``monthly_avg``)은 해당 월 관측의 산술평균, 당월이 기준일 전에 끝나면
  ``prelim``. ``rebase100``은 창 첫 관측 = 100.
- 창: 월별 2023-01~최신, 분기 2022-Q1~, 일별 최근 12개월, 연간 2019~.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .datastore.registry import ECB_DECISIONS
from .datastore.store import load_store, period_of_date, period_range

VERSION = "3.0.0"
SECTIONS = (
    "monetary",
    "inflation",
    "growth",
    "labour",
    "markets",
    "credit",
    "fiscal",
    "energy",
    "fx",
)
KINDS = ("line", "bar", "stacked_bar", "step", "dual_axis_line", "table_ref")
XTYPE = {"M": "month", "Q": "quarter", "A": "year", "D": "day", "C": "category"}
CSV_HEADER = ["date", "series_key", "value", "status", "tier", "source"]


# ---------------------------------------------------------------------------
# 공용 수치 헬퍼 (table_pack·facts에서도 사용)
# ---------------------------------------------------------------------------
def fmt(v: float | None, decimals: int, signed: bool = False) -> str:
    if v is None:
        return "–"
    s = f"{v:+,.{decimals}f}" if signed else f"{v:,.{decimals}f}"
    return s


def period_ko(p: str | None) -> str:
    if not p:
        return "–"
    if len(p) == 10:
        return f"{int(p[5:7])}월 {int(p[8:10])}일"
    if "-Q" in p:
        return f"{p[:4]}년 {p[-1]}분기"
    if len(p) == 7:
        return f"{p[:4]}년 {int(p[5:7])}월"
    return f"{p}년"


def last_valid(points: list[list]) -> tuple[str, float, str] | None:
    for p, v, st in reversed(points):
        if v is not None:
            return p, v, st
    return None


def monthly_avg(points: list[list], as_of: str) -> list[list]:
    """일별 → 월평균. 기준일 달의 월말 전 마감이면 prelim."""
    buckets: dict[str, list[float]] = {}
    last_day: dict[str, str] = {}
    for p, v, _ in points:
        if v is None:
            continue
        m = p[:7]
        buckets.setdefault(m, []).append(v)
        last_day[m] = p
    out = []
    for m in sorted(buckets):
        y, mm = int(m[:4]), int(m[5:7])
        nxt = date(y + (mm == 12), mm % 12 + 1, 1)
        month_end = (nxt - timedelta(days=1)).isoformat()
        complete = (
            as_of >= month_end or last_day[m] >= (nxt - timedelta(days=3)).isoformat()
        )
        vals = buckets[m]
        out.append(
            [m, round(sum(vals) / len(vals), 4), "final" if complete else "prelim"]
        )
    return out


def close_on_or_before(points: list[list], day: str) -> tuple[str, float] | None:
    best = None
    for p, v, _ in points:
        if v is None:
            continue
        if p <= day:
            best = (p, v)
        else:
            break
    return best


def pct_return(points: list[list], start_day: str, end_day: str) -> float | None:
    a = close_on_or_before(points, start_day)
    b = close_on_or_before(points, end_day)
    if not a or not b or a[1] == 0:
        return None
    return round((b[1] / a[1] - 1) * 100, 2)


def month_end_day(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def decision_dates(store: dict) -> list[dict]:
    """ECB 변경 발효일(FM B 계열) ↔ 결정일(정적 표, 없으면 발효일−6일 역산)."""
    s = store["series"]
    eff_to_dec = {e: d for d, e in ECB_DECISIONS}
    out = []
    prev = {"dfr": None, "mro": None, "mlf": None}
    rows: dict[str, dict] = {}
    for k in ("dfr", "mro", "mlf"):
        for p, v, _ in s.get(f"ecb_{k}_changes", {}).get("points", []):
            if v is None:
                continue
            rows.setdefault(p, {})[k] = v
    for eff in sorted(rows):
        r = rows[eff]
        dec = eff_to_dec.get(eff)
        basis = "table"
        if not dec:
            dec = (date.fromisoformat(eff) - timedelta(days=6)).isoformat()
            basis = "derived"
        rec = {"effective": eff, "decision": dec, "decision_basis": basis}
        for k in ("dfr", "mro", "mlf"):
            v = r.get(k, prev[k])
            rec[k] = v
            rec[f"{k}_prev"] = prev[k]
            rec[f"{k}_chg_bp"] = (
                round((v - prev[k]) * 100)
                if v is not None and prev[k] is not None
                else None
            )
            prev[k] = v
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# 차트 선언
# ---------------------------------------------------------------------------
@dataclass
class S:
    key: str
    name: str
    color: str = "primary"
    axis: str = "left"
    mark: str = "line"
    transform: str | None = None


@dataclass
class Chart:
    id: str
    section: str
    order: int
    kind: str
    freq: str  # M|Q|A|D|C
    series: list[S]
    title: Callable
    subtitle: Callable
    y: list[dict]
    window: str = "default"  # default|12m|2024|2022d|since2019
    headline: bool = False
    ref_lines: list[dict] = field(default_factory=list)
    notes: str = ""
    categories: list[tuple[str, str]] = field(default_factory=list)  # (key,label)
    decisions: bool = False
    optional: bool = False  # 입력 계열 전무 시 생략(llm_web 등)


def Y(unit: str, dec: int, label: str = "", axis: str = "left", **kw) -> dict:  # noqa: N802
    return {
        "id": axis,
        "label": label or unit,
        "unit": unit,
        "decimals": dec,
        "min": kw.get("min"),
        "max": kw.get("max"),
    }


def _stat_ko(st: str | None) -> str:
    return {"flash": " 속보", "prelim": " 잠정", "estimate": " 추정"}.get(st or "", "")


CHARTS: list[Chart] = [
    # ---------------- inflation ----------------
    Chart(
        "hicp_headline_core",
        "inflation",
        1,
        "line",
        "M",
        [
            S("ea_hicp_headline", "헤드라인", "primary"),
            S("ea_hicp_core", "근원(에너지·식품·주류·담배 제외)", "secondary"),
            S("ea_hicp_services", "서비스", "accent"),
        ],
        lambda c: (
            f"유로존 HICP {c.f('ea_hicp_headline')}%"
            f"{_stat_ko(c.st('ea_hicp_headline'))} ({c.pko('ea_hicp_headline')})"
        ),
        lambda c: f"근원 {c.f('ea_hicp_core')}% · 서비스 {c.f('ea_hicp_services')}%",
        [Y("% YoY", 1, "전년동월비(%)")],
        headline=True,
        ref_lines=[{"axis": "left", "y": 2.0, "label": "ECB 목표 2%"}],
    ),
    Chart(
        "hicp_components",
        "inflation",
        2,
        "line",
        "M",
        [
            S("ea_hicp_energy", "에너지", "negative"),
            S("ea_hicp_food", "식품·주류·담배", "accent"),
            S("ea_hicp_neig", "비에너지 공산품", "neutral"),
            S("ea_hicp_services", "서비스", "primary"),
        ],
        lambda c: (
            f"HICP 구성항목 — 에너지 {c.f('ea_hicp_energy')}%"
            f" ({c.pko('ea_hicp_energy')})"
        ),
        lambda c: (
            f"서비스 {c.f('ea_hicp_services')}% · 식품 {c.f('ea_hicp_food')}%"
            f" · 비에너지 공산품 {c.f('ea_hicp_neig')}%"
        ),
        [Y("% YoY", 1, "전년동월비(%)")],
    ),
    Chart(
        "hicp_contributions",
        "inflation",
        3,
        "stacked_bar",
        "M",
        [
            S("ea_hicp_ctr_energy", "에너지", "negative", mark="bar"),
            S("ea_hicp_ctr_food", "식품·주류·담배", "accent", mark="bar"),
            S("ea_hicp_ctr_neig", "비에너지 공산품", "neutral", mark="bar"),
            S("ea_hicp_ctr_services", "서비스", "primary", mark="bar"),
            S("ea_hicp_headline", "헤드라인(%)", "secondary", mark="line"),
        ],
        lambda c: (
            f"HICP 기여도 — 서비스 {c.f('ea_hicp_ctr_services')}%p · "
            f"에너지 {c.f('ea_hicp_ctr_energy')}%p ({c.pko('ea_hicp_ctr_energy')})"
        ),
        lambda c: (
            f"헤드라인 {c.f('ea_hicp_headline', dec=1)}% = 4개 주요 항목 기여도 합"
            " (반올림 차 존재)"
        ),
        [Y("%p", 2, "기여도(%p) / 헤드라인(%)")],
        window="2024",
        notes="기여도: Eurostat prc_hicp_ctr(ECOICOP v2, 연간 상승률에 대한 %p)",
    ),
    Chart(
        "hicp_countries",
        "inflation",
        4,
        "line",
        "M",
        [
            S("ea_hicp_headline", "유로존", "primary"),
            S("de_hicp_headline", "독일", "secondary"),
            S("fr_hicp_headline", "프랑스", "accent"),
            S("it_hicp_headline", "이탈리아", "neutral"),
            S("es_hicp_headline", "스페인", "negative"),
        ],
        lambda c: (
            f"국가별 HICP — 스페인 {c.f('es_hicp_headline')}%, "
            f"프랑스 {c.f('fr_hicp_headline')}% ({c.pko('es_hicp_headline')})"
        ),
        lambda c: (
            f"독일 {c.f('de_hicp_headline')}% · 이탈리아 "
            f"{c.f('it_hicp_headline')}% · 유로존 {c.f('ea_hicp_headline')}%"
        ),
        [Y("% YoY", 1, "전년동월비(%)")],
        ref_lines=[{"axis": "left", "y": 2.0, "label": "ECB 목표 2%"}],
    ),
    Chart(
        "hicp_mom",
        "inflation",
        5,
        "bar",
        "M",
        [S("ea_hicp_headline_mom", "전월비", "primary", mark="bar")],
        lambda c: (
            f"유로존 HICP 전월비 {c.f('ea_hicp_headline_mom', signed=True)}%"
            f" ({c.pko('ea_hicp_headline_mom')})"
        ),
        lambda c: "계절조정 전 원계열 전월비",
        [Y("% MoM", 1, "전월비(%)")],
        ref_lines=[{"axis": "left", "y": 0.0, "label": ""}],
    ),
    # ---------------- growth ----------------
    Chart(
        "gdp_qoq_countries",
        "growth",
        1,
        "bar",
        "Q",
        [
            S("ea_gdp_qoq", "유로존", "primary", mark="bar"),
            S("de_gdp_qoq", "독일", "secondary", mark="bar"),
            S("fr_gdp_qoq", "프랑스", "accent", mark="bar"),
            S("it_gdp_qoq", "이탈리아", "neutral", mark="bar"),
            S("es_gdp_qoq", "스페인", "negative", mark="bar"),
        ],
        lambda c: (
            f"실질 GDP 전기비 — 유로존 {c.f('ea_gdp_qoq', signed=True)}%"
            f" ({c.pko('ea_gdp_qoq')})"
        ),
        lambda c: (
            f"독일 {c.f('de_gdp_qoq', signed=True)}% · 프랑스 "
            f"{c.f('fr_gdp_qoq', signed=True)}% · 이탈리아 "
            f"{c.f('it_gdp_qoq', signed=True)}% · 스페인 "
            f"{c.f('es_gdp_qoq', signed=True)}%"
        ),
        [Y("% QoQ", 1, "전기비(%, 계절·역일조정)")],
        headline=True,
        ref_lines=[{"axis": "left", "y": 0.0, "label": ""}],
    ),
    Chart(
        "gdp_yoy_countries",
        "growth",
        2,
        "line",
        "Q",
        [
            S("ea_gdp_yoy", "유로존", "primary"),
            S("de_gdp_yoy", "독일", "secondary"),
            S("fr_gdp_yoy", "프랑스", "accent"),
            S("it_gdp_yoy", "이탈리아", "neutral"),
            S("es_gdp_yoy", "스페인", "negative"),
        ],
        lambda c: (
            f"실질 GDP 전년동기비 — 유로존 {c.f('ea_gdp_yoy')}% ({c.pko('ea_gdp_yoy')})"
        ),
        lambda c: (
            f"스페인 {c.f('es_gdp_yoy')}% · 독일 {c.f('de_gdp_yoy')}% · "
            f"프랑스 {c.f('fr_gdp_yoy')}%"
        ),
        [Y("% YoY", 1, "전년동기비(%)")],
        ref_lines=[{"axis": "left", "y": 0.0, "label": ""}],
    ),
    Chart(
        "gdp_contributions_ea",
        "growth",
        3,
        "stacked_bar",
        "Q",
        [
            S("ea_gdp_ctr_consumption", "가계소비", "primary", mark="bar"),
            S("ea_gdp_ctr_government", "정부소비", "neutral", mark="bar"),
            S("ea_gdp_ctr_investment", "총고정자본형성", "secondary", mark="bar"),
            S("ea_gdp_ctr_inventories", "재고변동", "accent", mark="bar"),
            S("ea_gdp_ctr_netexports", "순수출", "negative", mark="bar"),
            S("ea_gdp_qoq", "GDP 전기비(%)", "primary", mark="line"),
        ],
        lambda c: (
            f"유로존 GDP 기여도 — 순수출 "
            f"{c.f('ea_gdp_ctr_netexports', signed=True)}%p · 재고 "
            f"{c.f('ea_gdp_ctr_inventories', signed=True)}%p "
            f"({c.pko('ea_gdp_ctr_netexports')})"
        ),
        lambda c: (
            f"GDP 전기비 {c.f('ea_gdp_qoq', signed=True, dec=1)}% · 가계소비 "
            f"{c.f('ea_gdp_ctr_consumption', signed=True)}%p"
        ),
        [Y("%p", 2, "전기비 기여도(%p) / GDP(%)")],
        ref_lines=[{"axis": "left", "y": 0.0, "label": ""}],
        notes="기여도 합과 GDP 전기비는 통계 불일치로 다를 수 있음",
    ),
    Chart(
        "sentiment_esi_consumer",
        "growth",
        4,
        "dual_axis_line",
        "M",
        [
            S("ea_esi", "경기체감지수(ESI, 좌)", "primary"),
            S("ea_consumer_confidence", "소비자신뢰(우)", "secondary", axis="right"),
        ],
        lambda c: f"유로존 ESI {c.f('ea_esi')} ({c.pko('ea_esi')})",
        lambda c: f"소비자신뢰 {c.f('ea_consumer_confidence')} · 산업신뢰는 표 참조",
        [
            Y("index", 1, "ESI(장기평균=100)"),
            Y("balance", 1, "소비자신뢰(순응답)", axis="right"),
        ],
        ref_lines=[{"axis": "left", "y": 100.0, "label": "장기평균 100"}],
    ),
    Chart(
        "industrial_production",
        "growth",
        5,
        "line",
        "M",
        [
            S("ea_ip_yoy", "유로존", "primary"),
            S("de_ip_yoy", "독일", "secondary"),
        ],
        lambda c: (
            f"산업생산 전년비 — 유로존 {c.f('ea_ip_yoy', signed=True)}%, "
            f"독일 {c.f('de_ip_yoy', signed=True)}% ({c.pko('ea_ip_yoy')})"
        ),
        lambda c: "건설 제외 광공업(B-D), 역일조정",
        [Y("% YoY", 1, "전년동월비(%)")],
        ref_lines=[{"axis": "left", "y": 0.0, "label": ""}],
    ),
    Chart(
        "retail_sales",
        "growth",
        6,
        "bar",
        "M",
        [S("ea_retail_yoy", "소매판매량", "primary", mark="bar")],
        lambda c: (
            f"유로존 소매판매량 {c.f('ea_retail_yoy', signed=True)}% YoY"
            f" ({c.pko('ea_retail_yoy')})"
        ),
        lambda c: "자동차 제외 소매(G47), 역일조정",
        [Y("% YoY", 1, "전년동월비(%)")],
        ref_lines=[{"axis": "left", "y": 0.0, "label": ""}],
    ),
    Chart(
        "pmi_ea",
        "growth",
        7,
        "line",
        "M",
        [
            S("ea_pmi_composite", "종합", "primary"),
            S("ea_pmi_manufacturing", "제조업", "secondary"),
            S("ea_pmi_services", "서비스업", "accent"),
        ],
        lambda c: (
            f"유로존 종합 PMI {c.f('ea_pmi_composite')}"
            f"{_stat_ko(c.st('ea_pmi_composite'))} ({c.pko('ea_pmi_composite')})"
        ),
        lambda c: (
            f"제조업 {c.f('ea_pmi_manufacturing')} · 서비스업 {c.f('ea_pmi_services')}"
        ),
        [Y("index", 1, "지수(50=확장/위축 경계)")],
        headline=True,
        ref_lines=[{"axis": "left", "y": 50.0, "label": "50"}],
        optional=True,
        notes="S&P Global PMI는 무료 API 부재 — 웹 리서치 수집값(교차검증 대상)",
    ),
    Chart(
        "pmi_countries",
        "growth",
        8,
        "line",
        "M",
        [
            S("de_pmi_composite", "독일", "secondary"),
            S("fr_pmi_composite", "프랑스", "accent"),
            S("it_pmi_composite", "이탈리아", "neutral"),
            S("es_pmi_composite", "스페인", "negative"),
        ],
        lambda c: (
            f"국가별 종합 PMI — 독일 {c.f('de_pmi_composite')}, 프랑스 "
            f"{c.f('fr_pmi_composite')} ({c.pko('de_pmi_composite')})"
        ),
        lambda c: (
            f"이탈리아 {c.f('it_pmi_composite')} · 스페인 {c.f('es_pmi_composite')}"
        ),
        [Y("index", 1, "지수(50=경계)")],
        ref_lines=[{"axis": "left", "y": 50.0, "label": "50"}],
        optional=True,
        notes="S&P Global PMI — 웹 리서치 수집값",
    ),
    # ---------------- labour ----------------
    Chart(
        "unemployment",
        "labour",
        1,
        "line",
        "M",
        [
            S("ea_unemployment", "유로존", "primary"),
            S("de_unemployment", "독일", "secondary"),
            S("fr_unemployment", "프랑스", "accent"),
            S("it_unemployment", "이탈리아", "neutral"),
            S("es_unemployment", "스페인", "negative"),
        ],
        lambda c: (
            f"유로존 실업률 {c.f('ea_unemployment')}% ({c.pko('ea_unemployment')})"
        ),
        lambda c: (
            f"스페인 {c.f('es_unemployment')}% · 프랑스 "
            f"{c.f('fr_unemployment')}% · 이탈리아 {c.f('it_unemployment')}% · "
            f"독일 {c.f('de_unemployment')}%"
        ),
        [Y("%", 1, "경제활동인구 대비(%)")],
    ),
    # ---------------- monetary ----------------
    Chart(
        "ecb_policy_rates",
        "monetary",
        1,
        "step",
        "D",
        [
            S("ecb_dfr", "예금금리(DFR)", "primary", mark="step"),
            S("ecb_mro", "MRO", "secondary", mark="step"),
            S("ecb_mlf", "MLF", "neutral", mark="step"),
        ],
        lambda c: (
            f"ECB 예금금리 {c.f('ecb_dfr')}% (MRO {c.f('ecb_mro')}%, "
            f"MLF {c.f('ecb_mlf')}%)"
        ),
        lambda c: "적용일(발효일) 기준 일별 수준 · 결정일은 주석 표기",
        [Y("%", 2, "정책금리(%)")],
        window="2022d",
        headline=True,
        decisions=True,
    ),
    Chart(
        "estr_dfr",
        "monetary",
        2,
        "line",
        "D",
        [
            S("estr", "€STR", "primary"),
            S("ecb_dfr", "예금금리(DFR)", "neutral", mark="step"),
        ],
        lambda c: f"€STR {c.f('estr')}% vs DFR {c.f('ecb_dfr')}% ({c.pko('estr')})",
        lambda c: "최근 12개월 일별 · €STR은 익일 발표",
        [Y("%", 2, "금리(%)")],
        window="12m",
        decisions=True,
    ),
    Chart(
        "ois_path",
        "monetary",
        3,
        "line",
        "C",
        [S("estr_ois_implied_dfr", "OIS 내재 DFR", "primary")],
        lambda c: "OIS 내재 ECB 예금금리 경로",
        lambda c: "회의별 내재 금리(웹 리서치 수집)",
        [Y("%", 2, "내재 DFR(%)")],
        optional=True,
        notes="OIS 내재 경로는 무료 결정론 소스 부재 — 웹 리서치 수집값",
    ),
    # ---------------- markets ----------------
    Chart(
        "bund_2y_10y_daily",
        "markets",
        1,
        "line",
        "D",
        [
            S("de_bund_2y", "Bund 2년", "secondary"),
            S("de_bund_10y", "Bund 10년", "primary"),
        ],
        lambda c: (
            f"독일 국채 10년 {c.f('de_bund_10y')}% · 2년 "
            f"{c.f('de_bund_2y')}% ({c.pko('de_bund_10y')})"
        ),
        lambda c: "Bundesbank 스벤손 기간구조(상장 연방채) 일별, 최근 12개월",
        [Y("%", 2, "수익률(%)")],
        window="12m",
        headline=True,
    ),
    Chart(
        "bund_monthly_avg",
        "markets",
        2,
        "line",
        "M",
        [
            S("de_bund_2y", "Bund 2년(월평균)", "secondary", transform="monthly_avg"),
            S("de_bund_10y", "Bund 10년(월평균)", "primary", transform="monthly_avg"),
        ],
        lambda c: (
            f"Bund 월평균 — 10년 {c.f('de_bund_10y')}%, 2년 "
            f"{c.f('de_bund_2y')}% ({c.pko('de_bund_10y')})"
        ),
        lambda c: "일별 수익률의 월 산술평균 (당월은 기준일까지)",
        [Y("%", 2, "수익률(%)")],
        window="2024",
    ),
    Chart(
        "gov10y_monthly",
        "markets",
        3,
        "line",
        "M",
        [
            S("de_10y_m", "독일", "primary"),
            S("fr_10y_m", "프랑스", "accent"),
            S("it_10y_m", "이탈리아", "neutral"),
            S("es_10y_m", "스페인", "negative"),
        ],
        lambda c: (
            f"10년 국채수익률(월평균) — 프랑스 {c.f('fr_10y_m')}%, "
            f"이탈리아 {c.f('it_10y_m')}% ({c.pko('fr_10y_m')})"
        ),
        lambda c: f"독일 {c.f('de_10y_m')}% · 스페인 {c.f('es_10y_m')}%",
        [Y("%", 2, "수익률(%, 월평균)")],
        notes="ECB 수렴기준 장기금리(IRS) — 월평균만 무료 결정론 공급",
    ),
    Chart(
        "spreads_monthly",
        "markets",
        4,
        "line",
        "M",
        [
            S("fr_spread_m", "프랑스(OAT)", "accent"),
            S("it_spread_m", "이탈리아(BTP)", "neutral"),
            S("es_spread_m", "스페인(Bonos)", "negative"),
        ],
        lambda c: (
            f"대(對)독일 10년 스프레드 — 프랑스 {c.f('fr_spread_m')}bp, "
            f"이탈리아 {c.f('it_spread_m')}bp ({c.pko('fr_spread_m')})"
        ),
        lambda c: f"스페인 {c.f('es_spread_m')}bp · 월평균 수익률 차 × 100",
        [Y("bp", 0, "스프레드(bp, 월평균)")],
        headline=True,
        notes="OAT·BTP·Bonos 일별 10년물은 무료 결정론 소스 부재 → 월평균만 제공",
    ),
    Chart(
        "equity_indices_rebased",
        "markets",
        5,
        "line",
        "D",
        [
            S("stoxx600", "STOXX 600", "primary", transform="rebase100"),
            S("dax", "DAX", "secondary", transform="rebase100"),
            S("cac40", "CAC 40", "accent", transform="rebase100"),
            S("ftsemib", "FTSE MIB", "neutral", transform="rebase100"),
            S("ibex35", "IBEX 35", "negative", transform="rebase100"),
        ],
        lambda c: (
            f"유럽 주가지수 12개월 — STOXX 600 {c.f('stoxx600')}"
            f" (시작일=100, {c.pko('stoxx600')})"
        ),
        lambda c: (
            f"DAX {c.f('dax')} · CAC {c.f('cac40')} · MIB "
            f"{c.f('ftsemib')} · IBEX {c.f('ibex35')}"
        ),
        [Y("index", 1, "지수화(창 첫 거래일=100)")],
        window="12m",
    ),
    Chart(
        "sector_proxies_rebased",
        "markets",
        6,
        "line",
        "D",
        [
            S("stoxx600", "STOXX 600", "neutral", transform="rebase100"),
            S("banks_proxy", "은행(EXV1 ETF)", "primary", transform="rebase100"),
            S("autos_proxy", "자동차(EXV5 ETF)", "negative", transform="rebase100"),
        ],
        lambda c: (
            f"섹터 프록시 12개월 — 은행 {c.f('banks_proxy')}, 자동차 "
            f"{c.f('autos_proxy')} (시작일=100)"
        ),
        lambda c: f"STOXX 600 {c.f('stoxx600')} · 섹터는 iShares ETF 종가 프록시",
        [Y("index", 1, "지수화(창 첫 거래일=100)")],
        window="12m",
    ),
    Chart(
        "equity_returns",
        "markets",
        7,
        "bar",
        "C",
        [
            S("ret_month", "당월 수익률", "primary", mark="bar"),
            S("ret_ytd", "연초 이후", "secondary", mark="bar"),
        ],
        lambda c: (
            f"주가지수 수익률 — STOXX 600 당월 "
            f"{c.fcat('ret_month', 'stoxx600', signed=True)}%, 연초 이후 "
            f"{c.fcat('ret_ytd', 'stoxx600', signed=True)}%"
        ),
        lambda c: f"기준: {c.ctx['ret_basis']}",
        [Y("%", 1, "수익률(%)")],
        categories=[
            ("stoxx600", "STOXX 600"),
            ("sx5e", "Euro STOXX 50"),
            ("dax", "DAX"),
            ("cac40", "CAC 40"),
            ("ftsemib", "FTSE MIB"),
            ("ibex35", "IBEX 35"),
            ("banks_proxy", "은행(EXV1)"),
            ("autos_proxy", "자동차(EXV5)"),
        ],
        ref_lines=[{"axis": "left", "y": 0.0, "label": ""}],
    ),
    # ---------------- fx ----------------
    Chart(
        "eurusd_eurkrw_daily",
        "fx",
        1,
        "dual_axis_line",
        "D",
        [
            S("eurusd", "EUR/USD(좌)", "primary"),
            S("eurkrw", "EUR/KRW(우)", "accent", axis="right"),
        ],
        lambda c: (
            f"EUR/USD {c.f('eurusd')} · EUR/KRW {c.f('eurkrw')} ({c.pko('eurusd')})"
        ),
        lambda c: "ECB 기준환율 일별(14:15 CET), 최근 12개월",
        [
            Y("USD per EUR", 4, "EUR/USD"),
            Y("KRW per EUR", 2, "EUR/KRW", axis="right"),
        ],
        window="12m",
        headline=True,
    ),
    Chart(
        "fx_monthly_avg",
        "fx",
        2,
        "dual_axis_line",
        "M",
        [
            S("eurusd", "EUR/USD 월평균(좌)", "primary", transform="monthly_avg"),
            S(
                "eurkrw",
                "EUR/KRW 월평균(우)",
                "accent",
                axis="right",
                transform="monthly_avg",
            ),
        ],
        lambda c: (
            f"EUR/USD 월평균 {c.f('eurusd')} · EUR/KRW {c.f('eurkrw')}"
            f" ({c.pko('eurusd')})"
        ),
        lambda c: "ECB 기준환율 일별의 월 산술평균 (당월은 기준일까지)",
        [
            Y("USD per EUR", 4, "EUR/USD"),
            Y("KRW per EUR", 2, "EUR/KRW", axis="right"),
        ],
    ),
    Chart(
        "eurgbp_eurjpy_daily",
        "fx",
        3,
        "dual_axis_line",
        "D",
        [
            S("eurgbp", "EUR/GBP(좌)", "primary"),
            S("eurjpy", "EUR/JPY(우)", "secondary", axis="right"),
        ],
        lambda c: (
            f"EUR/GBP {c.f('eurgbp')} · EUR/JPY {c.f('eurjpy')} ({c.pko('eurgbp')})"
        ),
        lambda c: "ECB 기준환율 일별, 최근 12개월",
        [
            Y("GBP per EUR", 4, "EUR/GBP"),
            Y("JPY per EUR", 2, "EUR/JPY", axis="right"),
        ],
        window="12m",
    ),
    # ---------------- energy ----------------
    Chart(
        "brent_ttf_daily",
        "energy",
        1,
        "dual_axis_line",
        "D",
        [
            S("brent_dated", "Brent 현물(Dated, 좌)", "negative"),
            S("brent_fut", "Brent 근월물 선물(좌)", "neutral"),
            S("ttf", "TTF 가스 근월물(우)", "primary", axis="right"),
        ],
        lambda c: (
            f"Brent 현물 ${c.f('brent_dated')} ({c.pko('brent_dated')}) · "
            f"선물 ${c.f('brent_fut')} ({c.pko('brent_fut')})"
        ),
        lambda c: f"TTF €{c.f('ttf')}/MWh ({c.pko('ttf')}) · 현물·선물은 별개 가격",
        [
            Y("USD/bbl", 2, "Brent($/bbl)"),
            Y("EUR/MWh", 2, "TTF(€/MWh)", axis="right"),
        ],
        window="12m",
        headline=True,
        notes="Brent 현물=EIA Dated(FRED DCOILBRENTEU), 선물=ICE 근월물(BZ=F)",
    ),
    Chart(
        "brent_ttf_monthly_avg",
        "energy",
        2,
        "dual_axis_line",
        "M",
        [
            S(
                "brent_dated",
                "Brent 현물 월평균(좌)",
                "negative",
                transform="monthly_avg",
            ),
            S(
                "ttf",
                "TTF 월평균(우)",
                "primary",
                axis="right",
                transform="monthly_avg",
            ),
        ],
        lambda c: (
            f"Brent 현물 월평균 ${c.f('brent_dated')} · TTF "
            f"€{c.f('ttf')}/MWh ({c.pko('brent_dated')})"
        ),
        lambda c: "일별 가격의 월 산술평균 (당월은 기준일까지)",
        [
            Y("USD/bbl", 2, "Brent($/bbl)"),
            Y("EUR/MWh", 2, "TTF(€/MWh)", axis="right"),
        ],
        window="2024",
    ),
    # ---------------- credit ----------------
    Chart(
        "loan_growth",
        "credit",
        1,
        "line",
        "M",
        [
            S("ea_loans_nfc", "기업대출", "primary"),
            S("ea_loans_hh", "가계대출", "secondary"),
        ],
        lambda c: (
            f"유로존 은행대출 증가율 — 기업 {c.f('ea_loans_nfc')}%, "
            f"가계 {c.f('ea_loans_hh')}% ({c.pko('ea_loans_nfc')})"
        ),
        lambda c: "MFI 대출, 매각·증권화 조정 전년비",
        [Y("% YoY", 1, "전년비(%)")],
        ref_lines=[{"axis": "left", "y": 0.0, "label": ""}],
    ),
    Chart(
        "lending_rates",
        "credit",
        2,
        "line",
        "M",
        [
            S("ea_rate_nfc", "기업 차입비용", "primary"),
            S("ea_rate_mortgage", "주택담보 차입비용", "secondary"),
            S("ecb_dfr", "DFR(월평균)", "neutral", transform="monthly_avg"),
        ],
        lambda c: (
            f"차입비용 — 기업 {c.f('ea_rate_nfc')}%, 주담대 "
            f"{c.f('ea_rate_mortgage')}% ({c.pko('ea_rate_nfc')})"
        ),
        lambda c: f"DFR 월평균 {c.f('ecb_dfr')}% ({c.pko('ecb_dfr')})",
        [Y("%", 2, "금리(%)")],
    ),
    # ---------------- fiscal ----------------
    Chart(
        "gov_balance",
        "fiscal",
        1,
        "bar",
        "A",
        [
            S("ea_deficit", "유로존", "primary", mark="bar"),
            S("de_deficit", "독일", "secondary", mark="bar"),
            S("fr_deficit", "프랑스", "accent", mark="bar"),
            S("it_deficit", "이탈리아", "neutral", mark="bar"),
            S("es_deficit", "스페인", "negative", mark="bar"),
        ],
        lambda c: (
            f"재정수지(GDP 대비) — 프랑스 {c.f('fr_deficit')}% ({c.pko('fr_deficit')})"
        ),
        lambda c: (
            f"이탈리아 {c.f('it_deficit')}% · 스페인 {c.f('es_deficit')}% · "
            f"독일 {c.f('de_deficit')}% · 유로존 {c.f('ea_deficit')}%"
        ),
        [Y("% of GDP", 1, "GDP 대비(%)")],
        window="since2019",
        ref_lines=[{"axis": "left", "y": -3.0, "label": "EU 재정준칙 −3%"}],
    ),
    Chart(
        "gov_debt",
        "fiscal",
        2,
        "line",
        "Q",
        [
            S("ea_debt_q", "유로존", "primary"),
            S("de_debt_q", "독일", "secondary"),
            S("fr_debt_q", "프랑스", "accent"),
            S("it_debt_q", "이탈리아", "neutral"),
            S("es_debt_q", "스페인", "negative"),
        ],
        lambda c: (
            f"정부부채(GDP 대비) — 이탈리아 {c.f('it_debt_q')}%, 프랑스 "
            f"{c.f('fr_debt_q')}% ({c.pko('fr_debt_q')})"
        ),
        lambda c: (
            f"스페인 {c.f('es_debt_q')}% · 독일 {c.f('de_debt_q')}% · "
            f"유로존 {c.f('ea_debt_q')}%"
        ),
        [Y("% of GDP", 1, "GDP 대비(%)")],
        window="since2019",
        ref_lines=[{"axis": "left", "y": 60.0, "label": "EU 재정준칙 60%"}],
    ),
]


# ---------------------------------------------------------------------------
# 빌드
# ---------------------------------------------------------------------------
class TitleCtx:
    def __init__(self, series: dict[str, dict], y: list[dict], extra: dict):
        self.s = series
        self.dec = {d["id"]: d["decimals"] for d in y}
        self.ctx = extra

    def _last(self, key):
        r = self.s[key]
        for lab, v, st in zip(
            reversed(r["_labels"]),
            reversed(r["values"]),
            reversed(r["status"]),
            strict=True,
        ):
            if v is not None:
                return lab, v, st
        return None, None, None

    def f(self, key: str, signed: bool = False, dec: int | None = None) -> str:
        """최신값 문자열. 자릿수 = y축 decimals(또는 계열 저장 decimals ``dec``)."""
        _, v, _ = self._last(key)
        return fmt(v, self.dec[self.s[key]["axis"]] if dec is None else dec, signed)

    def fcat(self, key: str, cat: str, signed: bool = False) -> str:
        r = self.s[key]
        v = r["values"][r["_labels"].index(cat)]
        return fmt(v, self.dec[r["axis"]], signed)

    def st(self, key: str) -> str | None:
        return self._last(key)[2]

    def pko(self, key: str) -> str:
        return period_ko(self._last(key)[0])


def _window(ch: Chart, as_of: str) -> tuple[str, str | None]:
    if ch.freq == "D":
        if ch.window == "2022d":
            return "2022-01-01", as_of
        return (date.fromisoformat(as_of) - timedelta(days=365)).isoformat(), as_of
    if ch.freq == "M":
        return ("2024-01" if ch.window == "2024" else "2023-01"), None
    if ch.freq == "Q":
        return ("2019-Q1" if ch.window == "since2019" else "2022-Q1"), None
    if ch.freq == "A":
        return "2019", None
    return "", None


def _transform(rec: dict, s: S, freq: str, frm: str, as_of: str) -> list[list]:
    pts = rec["points"]
    if s.transform == "monthly_avg":
        pts = monthly_avg(pts, as_of)
    if freq == "D":
        pts = [p for p in pts if frm <= p[0] <= as_of]
    if s.transform == "rebase100":
        base = next((v for _, v, _ in pts if v is not None), None)
        pts = (
            [
                [p, round(v / base * 100, 4) if v is not None else None, st]
                for p, v, st in pts
            ]
            if base
            else []
        )
    return pts


def _returns(store: dict, month: str, as_of: str) -> tuple[dict, dict, str]:
    s = store["series"]
    end = min(month_end_day(month), as_of)
    start_m = month_end_day(prev_month(month))
    start_y = f"{int(month[:4]) - 1}-12-31"
    rm, ry = {}, {}
    last_days = []
    for k in (
        "stoxx600",
        "sx5e",
        "dax",
        "cac40",
        "ftsemib",
        "ibex35",
        "banks_proxy",
        "autos_proxy",
    ):
        if k not in s:
            continue
        pts = s[k]["points"]
        rm[k] = pct_return(pts, start_m, end)
        ry[k] = pct_return(pts, start_y, end)
        c = close_on_or_before(pts, end)
        if c:
            last_days.append(c[0])
    basis_day = max(last_days) if last_days else end
    basis = (
        f"{period_ko(basis_day)} 종가 vs 전월말·전년말 종가"
        if last_days
        else "데이터 없음"
    )
    return rm, ry, basis


def build_chart(ch: Chart, store: dict, as_of: str, month: str) -> dict | None:
    ss = store["series"]
    frm, to = _window(ch, as_of)
    extra: dict = {}
    series_out: dict[str, dict] = {}
    if ch.freq == "C" and ch.categories:
        rm, ry, basis = _returns(store, month, as_of)
        extra["ret_basis"] = basis
        labels = [k for k, _ in ch.categories]
        for s, data in ((ch.series[0], rm), (ch.series[1], ry)):
            vals = [data.get(k) for k in labels]
            series_out[s.key] = {
                "s": s,
                "rec": {
                    "tier": "market",
                    "source": "Yahoo Finance(yfinance)",
                    "dataset": "종가 기반 계산",
                    "url": "https://finance.yahoo.com",
                    "decimals": 1,
                },
                "values": vals,
                "status": ["spot" if v is not None else None for v in vals],
                "_labels": labels,
            }
        x_labels = labels
        x = {
            "type": "category",
            "from": labels[0],
            "to": labels[-1],
            "labels": labels,
            "label_ko": [lab for _, lab in ch.categories],
        }
    else:
        present = [s for s in ch.series if s.key in ss]
        if not present:
            return None
        if ch.freq == "C":  # 범주형 웹 계열(OIS 경로)
            rec = ss[present[0].key]
            x_labels = [p[0] for p in rec["points"]]
        pts_by: dict[str, list[list]] = {}
        for s in present:
            pts_by[s.key] = _transform(ss[s.key], s, ch.freq, frm, as_of)
        if ch.freq in ("M", "Q", "A"):
            lasts = [p[-1][0] for p in pts_by.values() if p]
            to = max(lasts) if lasts else frm
            x_labels = period_range(ch.freq, frm, to)
        elif ch.freq == "D":
            x_labels = sorted({p[0] for pts in pts_by.values() for p in pts})
        for s in ch.series:
            if s.key not in ss:
                continue
            m = {p[0]: p for p in pts_by[s.key]}
            vals = [m[x][1] if x in m else None for x in x_labels]
            sts = [
                m[x][2] if x in m and m[x][1] is not None else None for x in x_labels
            ]
            series_out[s.key] = {
                "s": s,
                "rec": ss[s.key],
                "values": vals,
                "status": sts,
                "_labels": x_labels,
            }
        if not x_labels:
            return None
        x = {
            "type": XTYPE[ch.freq],
            "from": x_labels[0],
            "to": x_labels[-1],
            "labels": x_labels,
        }
    for k, v in series_out.items():
        v["axis"] = v["s"].axis
    tctx = TitleCtx(series_out, ch.y, extra)
    try:
        title, subtitle = ch.title(tctx), ch.subtitle(tctx)
    except Exception as exc:  # noqa: BLE001 — 입력 결측 시 제목 템플릿 실패
        return {"_error": f"title: {type(exc).__name__}: {exc}"}
    out_series = []
    for k, v in series_out.items():
        s, rec = v["s"], v["rec"]
        last = next(
            (
                lab
                for lab, val in zip(
                    reversed(v["_labels"]), reversed(v["values"]), strict=True
                )
                if val is not None
            ),
            None,
        )
        out_series.append(
            {
                "key": k,
                "name_ko": s.name,
                "axis": s.axis,
                "mark": s.mark,
                "color_role": s.color,
                "gap": "break",
                "freq": ch.freq,
                "transform": s.transform
                or ("return_pct" if ch.freq == "C" and ch.categories else None),
                "tier": rec["tier"],
                "source": rec["source"],
                "dataset": rec.get("dataset", ""),
                "url": rec.get("url", ""),
                "decimals": rec.get("decimals", 1),
                "last_period": last,
                "values": v["values"],
                "status": v["status"],
            }
        )
    annotations = []
    for o in out_series:
        for lab, st in zip(x_labels, o["status"], strict=True):
            if st == "flash":
                annotations.append(
                    {"x": lab, "series": o["key"], "label": "속보", "kind": "flash"}
                )
    if ch.decisions:
        for d in decision_dates(store):
            if x_labels[0] <= d["effective"] <= x_labels[-1]:
                annotations.append(
                    {
                        "x": d["effective"],
                        "series": "ecb_dfr",
                        "label": f"결정 {d['decision']} · 발효 {d['effective']}",
                        "kind": "decision",
                    }
                )
    srcs: list[str] = []
    for o in out_series:
        tag = f"{o['source']}({o['dataset']})" if o["dataset"] else o["source"]
        if tag not in srcs:
            srcs.append(tag)
    foot = f"자료: {', '.join(srcs)} · 기준일 {as_of}"
    if ch.notes:
        foot += f" · {ch.notes}"
    return {
        "id": ch.id,
        "section": ch.section,
        "order": ch.order,
        "kind": ch.kind,
        "headline": ch.headline,
        "title": title,
        "subtitle": subtitle,
        "x": x,
        "y": ch.y,
        "series": out_series,
        "reference_lines": ch.ref_lines,
        "annotations": annotations,
        "footnote": foot,
        "data_csv": f"data/charts/{ch.id}.csv",
        "as_of": as_of,
    }


def write_csv(chart: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for i, lab in enumerate(chart["x"]["labels"]):
            for s in chart["series"]:
                v = s["values"][i]
                w.writerow(
                    [
                        lab,
                        s["key"],
                        "" if v is None else repr(float(v)),
                        s["status"][i] or "",
                        s["tier"],
                        s["source"],
                    ]
                )


def build(root: Path, charts: list[Chart] | None = None) -> dict:
    root = Path(root)
    store = load_store(root)
    ed_path = root / "edition.json"
    month = (
        json.loads(ed_path.read_text(encoding="utf-8"))["month"]
        if ed_path.exists()
        else period_of_date("M", store["as_of"])
    )
    as_of = store["as_of"]
    out: list[dict] = []
    skipped: list[dict] = []
    for ch in charts if charts is not None else CHARTS:
        c = build_chart(ch, store, as_of, month)
        if c is None:
            skipped.append(
                {
                    "id": ch.id,
                    "reason": "입력 계열 없음"
                    + (" (선택 차트)" if ch.optional else ""),
                }
            )
            continue
        if "_error" in c:
            skipped.append({"id": ch.id, "reason": c["_error"]})
            continue
        write_csv(c, root / c["data_csv"])
        out.append(c)
    doc = {
        "version": VERSION,
        "as_of": as_of,
        "month": month,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "store_generated_at": store.get("generated_at"),
        "charts": out,
        "skipped": skipped,
    }
    (root / "data" / "chart_pack.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="chart_pack")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", required=True)
    b.add_argument("--charts-only", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root)
    doc = build(root)
    print(f"charts {len(doc['charts'])} skipped {len(doc['skipped'])}")
    for s in doc["skipped"]:
        print("  SKIP", s["id"], s["reason"])
    if not a.charts_only:
        from . import facts, table_pack

        t = table_pack.build(root)
        print(f"tables {len(t['tables'])}")
        f = facts.build(root)
        print(f"facts {len(f['facts'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
