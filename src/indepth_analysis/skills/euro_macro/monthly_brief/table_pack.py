"""표 팩 생성기 — ``ROOT/data/table_pack.json`` + ``ROOT/data/tables.md``.

    M=indepth_analysis.skills.euro_macro.monthly_brief.table_pack
    uv run python -m $M build --root reports/euro_macro/monthly_brief/2026-09

스키마::

    {"version","as_of","month","generated_at",
     "tables":[{"id","section","order","title","subtitle",
       "columns":[{"key","label","unit","decimals","signed","bold"}],
       "rows":[{<key>: value, ...}],       # 수치는 원값(float), 표시 자릿수는 columns
       "checks":[{"col","op":"diff|diff_bp|pct","a","b"}],  # 검증기가 재계산
       "footnote","sources":[str]}]}

변화 열은 전부 코드 계산(``checks``에 산식 선언 → ``validate_pack``이 재계산 대조).
``to_markdown(table)``은 부록용 마크다운 표를 만든다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .chart_pack import (
    close_on_or_before,
    decision_dates,
    fmt,
    last_valid,
    month_end_day,
    pct_return,
    period_ko,
    prev_month,
)
from .datastore.registry import GEO_KO
from .datastore.store import load_store, period_index

VERSION = "3.0.0"
GEOS = ("EA", "DE", "FR", "IT", "ES")
CAL_MAP = {  # 로컬 캘린더 series_id → 다음 발표일 열
    "ea_hicp_headline": "EU.HICP_YOY",
    "ea_hicp_core": "EU.CORE_CPI_YOY",
    "ea_unemployment": "EU.UNRATE",
    "ea_gdp_qoq": "EU.GDP_QOQ",
    "ea_pmi_manufacturing": "EU.PMI_MFG",
    "ea_pmi_services": "EU.PMI_SVC",
}


def col(key, label, unit="", decimals=1, signed=False, bold=False) -> dict:
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "decimals": decimals,
        "signed": signed,
        "bold": bold,
    }


def _diff(a, b, scale=1.0, nd=4):
    if a is None or b is None:
        return None
    return round((a - b) * scale, nd)


def _prev_valid(points, period):
    """period 직전 비결측 관측."""
    prev = None
    for p, v, st in points:
        if p >= period:
            break
        if v is not None:
            prev = (p, v, st)
    return prev


def _series_lp(store, sid):
    s = store["series"].get(sid)
    if not s:
        return None, None
    lv = last_valid(s["points"])
    if not lv:
        return s, None
    pv = _prev_valid(s["points"], lv[0])
    return s, (lv, pv)


def _val_at(store, sid, period):
    s = store["series"].get(sid)
    if not s:
        return None
    for p, v, _ in s["points"]:
        if p == period:
            return v
    return None


def _status_ko(st):
    return {
        "final": "확정",
        "flash": "속보",
        "prelim": "잠정",
        "spot": "시장",
        "estimate": "추정",
    }.get(st, st or "")


# ---------------------------------------------------------------------------
# (a) 핵심 지표
# ---------------------------------------------------------------------------
KEY_INDICATORS = [
    ("ea_hicp_headline", "HICP 헤드라인", 1),
    ("ea_hicp_core", "근원 HICP", 1),
    ("ea_hicp_services", "HICP 서비스", 1),
    ("ea_hicp_energy", "HICP 에너지", 1),
    ("ea_gdp_qoq", "실질 GDP 전기비", 1),
    ("ea_gdp_yoy", "실질 GDP 전년동기비", 1),
    ("ea_unemployment", "실업률", 1),
    ("ea_esi", "경기체감지수(ESI)", 1),
    ("ea_consumer_confidence", "소비자신뢰", 1),
    ("ea_ip_yoy", "산업생산 전년비", 1),
    ("ea_retail_yoy", "소매판매량 전년비", 1),
    ("ea_pmi_composite", "종합 PMI", 1),
    ("ea_pmi_manufacturing", "제조업 PMI", 1),
    ("ea_pmi_services", "서비스업 PMI", 1),
    ("ea_loans_nfc", "기업대출 증가율", 1),
    ("ea_loans_hh", "가계대출 증가율", 1),
]


def t_key_indicators(store) -> dict:
    cal = store.get("calendar", {}).get("next_releases", {})
    rows = []
    for sid, label, _ in KEY_INDICATORS:
        s, lp = _series_lp(store, sid)
        if not s or not lp:
            continue
        (p, v, st), pv = lp
        rows.append(
            {
                "indicator": label,
                "unit": s["unit"],
                "period": p,
                "latest": v,
                "prev_period": pv[0] if pv else None,
                "previous": pv[1] if pv else None,
                "change": _diff(v, pv[1] if pv else None),
                "status": _status_ko(st),
                "tier": s["tier"],
                "next_release": cal.get(CAL_MAP.get(sid, ""), None),
                "series": sid,
            }
        )
    return {
        "id": "key_indicators",
        "section": "summary",
        "order": 1,
        "title": "유로존 핵심 지표 — 최신치와 직전치",
        "subtitle": "변화 = 최신 − 직전(단위 그대로, %는 %p)",
        "columns": [
            col("indicator", "지표", bold=True),
            col("period", "기간"),
            col("latest", "최신", decimals=1, bold=True),
            col("previous", "직전", decimals=1),
            col("change", "변화", decimals=1, signed=True),
            col("unit", "단위"),
            col("status", "상태"),
            col("next_release", "다음 발표"),
        ],
        "rows": rows,
        "checks": [{"col": "change", "op": "diff", "a": "latest", "b": "previous"}],
        "footnote": "다음 발표일은 로컬 경제 캘린더 기준(미등록 시 공란). "
        "PMI는 웹 리서치 수집값(tier llm_web)",
        "sources": sorted({store["series"][r["series"]]["source"] for r in rows}),
    }


# ---------------------------------------------------------------------------
# (b) 국가 매트릭스
# ---------------------------------------------------------------------------
def t_country_matrix(store) -> dict:
    rows = []
    for g in GEOS:
        gl = g.lower()

        def lv(sid):
            s = store["series"].get(sid)
            r = last_valid(s["points"]) if s else None
            return (r[1], r[0]) if r else (None, None)

        gdp, gdp_p = lv(f"{gl}_gdp_qoq")
        hicp, hicp_p = lv(f"{gl}_hicp_headline")
        un, un_p = lv(f"{gl}_unemployment")
        y10, y10_p = lv(f"{gl}_10y_m") if g != "EA" else (None, None)
        sp, sp_p = lv(f"{gl}_spread_m") if g not in ("EA", "DE") else (None, None)
        de, de_p = lv(f"{gl}_deficit")
        db, db_p = lv(f"{gl}_debt_q")
        rows.append(
            {
                "geo": GEO_KO[g],
                "gdp_qoq": gdp,
                "hicp": hicp,
                "unemployment": un,
                "y10": y10,
                "spread": sp,
                "deficit": de,
                "debt": db,
                "_periods": {
                    "gdp_qoq": gdp_p,
                    "hicp": hicp_p,
                    "unemployment": un_p,
                    "y10": y10_p,
                    "spread": sp_p,
                    "deficit": de_p,
                    "debt": db_p,
                },
            }
        )
    per = {
        k: rows[0]["_periods"][k] or rows[1]["_periods"][k] for k in rows[0]["_periods"]
    }
    sub = " · ".join(
        f"{lab} {period_ko(per[k])}"
        for k, lab in (
            ("gdp_qoq", "GDP"),
            ("hicp", "HICP"),
            ("unemployment", "실업"),
            ("y10", "10년물"),
            ("deficit", "재정수지"),
            ("debt", "부채"),
        )
    )
    return {
        "id": "country_matrix",
        "section": "growth",
        "order": 1,
        "title": "국가별 거시 매트릭스",
        "subtitle": f"기준 기간: {sub}",
        "columns": [
            col("geo", "국가", bold=True),
            col("gdp_qoq", "GDP 전기비", "%", 1, signed=True),
            col("hicp", "HICP", "% YoY", 1),
            col("unemployment", "실업률", "%", 1),
            col("y10", "10년 국채(월평균)", "%", 2),
            col("spread", "대독 스프레드", "bp", 0),
            col("deficit", "재정수지", "% GDP", 1, signed=True),
            col("debt", "정부부채", "% GDP", 1),
        ],
        "rows": rows,
        "checks": [],
        "footnote": "국가별 최신 기간은 행마다 `_periods`에 기록. 유로존 10년물은 단일 "
        "지표 부재로 공란",
        "sources": ["Eurostat", "ECB Data Portal"],
    }


# ---------------------------------------------------------------------------
# (c) 금리·수익률·환율 수준과 변화
# ---------------------------------------------------------------------------
LEVELS = [
    ("ecb_dfr", "ECB 예금금리", "%", 2, "bp"),
    ("estr", "€STR", "%", 3, "bp"),
    ("de_bund_2y", "Bund 2년", "%", 2, "bp"),
    ("de_bund_10y", "Bund 10년", "%", 2, "bp"),
    ("ea_aaa_10y", "유로존 AAA 10년(YC)", "%", 2, "bp"),
    ("eurusd", "EUR/USD", "", 4, "pct"),
    ("eurkrw", "EUR/KRW", "", 2, "pct"),
    ("eurgbp", "EUR/GBP", "", 4, "pct"),
    ("eurjpy", "EUR/JPY", "", 2, "pct"),
    ("brent_dated", "Brent 현물($)", "", 2, "pct"),
    ("brent_fut", "Brent 선물($)", "", 2, "pct"),
    ("ttf", "TTF(€/MWh)", "", 2, "pct"),
]


def _shift(day: str, months: int) -> str:
    d = date.fromisoformat(day)
    m = d.month - months
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    import calendar

    return date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def t_rates_fx(store) -> dict:
    rows = []
    for sid, label, unit, dec, kind in LEVELS:
        s = store["series"].get(sid)
        if not s:
            continue
        lv = last_valid(s["points"])
        if not lv:
            continue
        day = lv[0]
        refs = {
            "m1": close_on_or_before(s["points"], _shift(day, 1)),
            "m3": close_on_or_before(s["points"], _shift(day, 3)),
            "ytd": close_on_or_before(s["points"], f"{int(day[:4]) - 1}-12-31"),
        }
        row = {
            "item": label,
            "date": day,
            "level": lv[1],
            "kind": kind,
            "series": sid,
            "_decimals": {"level": dec},
        }
        for k, r in refs.items():
            row[f"{k}_ref"] = r[1] if r else None
            row[f"{k}_ref_date"] = r[0] if r else None
            if kind == "bp":
                row[f"chg_{k}"] = _diff(lv[1], r[1] if r else None, 100, 1)
            else:
                row[f"chg_{k}"] = (
                    round((lv[1] / r[1] - 1) * 100, 2) if r and r[1] else None
                )
        rows.append(row)
    checks = []
    for k in ("m1", "m3", "ytd"):
        checks.append(
            {
                "col": f"chg_{k}",
                "op": "auto",
                "a": "level",
                "b": f"{k}_ref",
                "kind_col": "kind",
            }
        )
    return {
        "id": "rates_fx_levels",
        "section": "markets",
        "order": 1,
        "title": "정책금리·수익률·환율·원자재 — 수준과 변화",
        "subtitle": "금리 변화는 bp, 환율·원자재 변화는 %. 기준: 각 계열 최신 관측일",
        "columns": [
            col("item", "항목", bold=True),
            col("date", "기준일"),
            col("level", "수준", decimals=2, bold=True),
            col("chg_m1", "1개월", decimals=1, signed=True),
            col("chg_m3", "3개월", decimals=1, signed=True),
            col("chg_ytd", "연초 이후", decimals=1, signed=True),
        ],
        "rows": rows,
        "checks": checks,
        "footnote": "1개월·3개월 전 기준은 해당일 또는 직전 영업일 관측. 연초 이후는 "
        "전년 12월 31일(또는 직전 영업일) 대비",
        "sources": sorted({store["series"][r["series"]]["source"] for r in rows}),
    }


# ---------------------------------------------------------------------------
# (d) HICP 구성·기여도
# ---------------------------------------------------------------------------
def t_hicp(store) -> dict:
    s = store["series"].get("ea_hicp_headline")
    lv = last_valid(s["points"]) if s else None
    period = lv[0] if lv else None
    prev = _prev_valid(s["points"], period)[0] if lv else None
    rows = []
    for label, rate, ctr in (
        ("헤드라인", "ea_hicp_headline", None),
        ("근원", "ea_hicp_core", None),
        ("에너지", "ea_hicp_energy", "ea_hicp_ctr_energy"),
        ("식품·주류·담배", "ea_hicp_food", "ea_hicp_ctr_food"),
        ("비에너지 공산품", "ea_hicp_neig", "ea_hicp_ctr_neig"),
        ("서비스", "ea_hicp_services", "ea_hicp_ctr_services"),
    ):
        cur, pv = _val_at(store, rate, period), _val_at(store, rate, prev)
        c_cur = _val_at(store, ctr, period) if ctr else None
        c_pv = _val_at(store, ctr, prev) if ctr else None
        rows.append(
            {
                "component": label,
                "rate": cur,
                "rate_prev": pv,
                "rate_chg": _diff(cur, pv),
                "ctr": c_cur,
                "ctr_prev": c_pv,
                "ctr_chg": _diff(c_cur, c_pv),
            }
        )
    ctr_sum = [r["ctr"] for r in rows if r["ctr"] is not None]
    rows.append(
        {
            "component": "기여도 합(4개 항목)",
            "rate": None,
            "rate_prev": None,
            "rate_chg": None,
            "ctr": round(sum(ctr_sum), 4) if len(ctr_sum) == 4 else None,
            "ctr_prev": None,
            "ctr_chg": None,
        }
    )
    status = _status_ko(lv[2]) if lv else ""
    return {
        "id": "hicp_components",
        "section": "inflation",
        "order": 1,
        "title": f"HICP 구성항목·기여도 — {period_ko(period)} vs {period_ko(prev)}",
        "subtitle": f"상승률 % YoY, 기여도 %p · 최신 상태 {status}",
        "columns": [
            col("component", "항목", bold=True),
            col("rate", period_ko(period), "% YoY", 1, bold=True),
            col("rate_prev", period_ko(prev), "% YoY", 1),
            col("rate_chg", "변화", "%p", 1, signed=True),
            col("ctr", f"기여도 {period_ko(period)}", "%p", 2),
            col("ctr_prev", f"기여도 {period_ko(prev)}", "%p", 2),
            col("ctr_chg", "기여도 변화", "%p", 2, signed=True),
        ],
        "rows": rows,
        "checks": [
            {"col": "rate_chg", "op": "diff", "a": "rate", "b": "rate_prev"},
            {"col": "ctr_chg", "op": "diff", "a": "ctr", "b": "ctr_prev"},
        ],
        "footnote": "Eurostat prc_hicp_minr(상승률)·prc_hicp_ctr(기여도), ECOICOP v2. "
        "기여도 합과 헤드라인 차이는 반올림·가중치 효과",
        "sources": ["Eurostat"],
    }


# ---------------------------------------------------------------------------
# (e) 주가 수익률
# ---------------------------------------------------------------------------
EQ = [
    ("stoxx600", "STOXX 600"),
    ("sx5e", "Euro STOXX 50"),
    ("dax", "DAX"),
    ("cac40", "CAC 40"),
    ("ftsemib", "FTSE MIB"),
    ("ibex35", "IBEX 35"),
    ("banks_proxy", "은행(EXV1 ETF)"),
    ("autos_proxy", "자동차(EXV5 ETF)"),
    ("brent_fut", "Brent 선물"),
    ("ttf", "TTF 가스"),
]


def t_market_returns(store, month, as_of) -> dict:
    end = min(month_end_day(month), as_of)
    sm = month_end_day(prev_month(month))
    sy = f"{int(month[:4]) - 1}-12-31"
    rows = []
    for sid, label in EQ:
        s = store["series"].get(sid)
        if not s:
            continue
        pts = s["points"]
        c_end, c_m, c_y = (
            close_on_or_before(pts, end),
            close_on_or_before(pts, sm),
            close_on_or_before(pts, sy),
        )
        rows.append(
            {
                "item": label,
                "close_date": c_end[0] if c_end else None,
                "close": c_end[1] if c_end else None,
                "prev_month_close": c_m[1] if c_m else None,
                "prev_year_close": c_y[1] if c_y else None,
                "ret_month": pct_return(pts, sm, end),
                "ret_ytd": pct_return(pts, sy, end),
                "series": sid,
            }
        )
    return {
        "id": "market_returns",
        "section": "markets",
        "order": 2,
        "title": f"주가지수·섹터·원자재 수익률 — {period_ko(month)}",
        "subtitle": "당월 = 전월말 종가 대비, 연초 이후 = 전년말 종가 대비",
        "columns": [
            col("item", "항목", bold=True),
            col("close_date", "기준일"),
            col("close", "종가", decimals=2),
            col("ret_month", "당월(%)", "%", 2, signed=True, bold=True),
            col("ret_ytd", "연초 이후(%)", "%", 2, signed=True),
        ],
        "rows": rows,
        "checks": [
            {"col": "ret_month", "op": "pct", "a": "close", "b": "prev_month_close"},
            {"col": "ret_ytd", "op": "pct", "a": "close", "b": "prev_year_close"},
        ],
        "footnote": "Yahoo Finance 일별 종가. 은행·자동차는 iShares STOXX Europe 600 "
        "섹터 ETF 프록시",
        "sources": ["Yahoo Finance(yfinance)"],
    }


# ---------------------------------------------------------------------------
# (f) ECB 결정 이력
# ---------------------------------------------------------------------------
def t_ecb_history(store, edition: dict) -> dict:
    rows = []
    for d in decision_dates(store):
        if d["effective"] < "2022-01-01":
            continue
        rows.append(
            {
                "decision": d["decision"],
                "effective": d["effective"],
                "dfr": d["dfr"],
                "mro": d["mro"],
                "mlf": d["mlf"],
                "dfr_prev": d["dfr_prev"],
                "mro_prev": d["mro_prev"],
                "dfr_chg_bp": d["dfr_chg_bp"],
                "mro_chg_bp": d["mro_chg_bp"],
                "basis": "정적 표" if d["decision_basis"] == "table" else "발효일−6일",
            }
        )
    last = (edition.get("ecb") or {}).get("last_meeting")
    nxt = (edition.get("ecb") or {}).get("next_meeting")
    return {
        "id": "ecb_decisions",
        "section": "monetary",
        "order": 1,
        "title": "ECB 정책금리 변경 이력 (2022~)",
        "subtitle": f"직전 회의 {last or '–'} · 다음 회의 {nxt or '–'}",
        "columns": [
            col("decision", "결정일", bold=True),
            col("effective", "발효일"),
            col("dfr", "DFR", "%", 2, bold=True),
            col("mro", "MRO", "%", 2),
            col("mlf", "MLF", "%", 2),
            col("dfr_chg_bp", "DFR 변화", "bp", 0, signed=True),
            col("mro_chg_bp", "MRO 변화", "bp", 0, signed=True),
            col("basis", "결정일 근거"),
        ],
        "rows": rows,
        "checks": [
            {"col": "dfr_chg_bp", "op": "diff_bp", "a": "dfr", "b": "dfr_prev"},
            {"col": "mro_chg_bp", "op": "diff_bp", "a": "mro", "b": "mro_prev"},
        ],
        "footnote": "수준·발효일: ECB FM(변경일 계열). 결정일: 2022~2025 정적 표, "
        "이후는 발효일−6일 규칙. 2024-09 MRO·MLF 추가 인하는 운영체계 개편(DFR-MRO 폭 "
        "15bp로 축소) 반영",
        "sources": ["ECB Data Portal"],
    }


# ---------------------------------------------------------------------------
# (g) 신용
# ---------------------------------------------------------------------------
def t_credit(store) -> dict:
    rows = []
    for sid, label in (
        ("ea_loans_nfc", "기업대출 증가율(% YoY)"),
        ("ea_loans_hh", "가계대출 증가율(% YoY)"),
        ("ea_rate_nfc", "기업 차입비용(%)"),
        ("ea_rate_mortgage", "주택담보 차입비용(%)"),
    ):
        s, lp = _series_lp(store, sid)
        if not s or not lp:
            continue
        (p, v, st), pv = lp
        y_ago_p = f"{int(p[:4]) - 1}{p[4:]}"
        ya = _val_at(store, sid, y_ago_p)
        rows.append(
            {
                "item": label,
                "period": p,
                "latest": v,
                "previous": pv[1] if pv else None,
                "change": _diff(v, pv[1] if pv else None),
                "year_ago": ya,
                "change_y": _diff(v, ya),
                "status": _status_ko(st),
                "series": sid,
            }
        )
    return {
        "id": "credit",
        "section": "credit",
        "order": 1,
        "title": "유로존 은행 신용 — 대출 증가율과 차입비용",
        "subtitle": "변화 단위 %p",
        "columns": [
            col("item", "항목", bold=True),
            col("period", "기간"),
            col("latest", "최신", decimals=2, bold=True),
            col("previous", "전월", decimals=2),
            col("change", "전월 대비", decimals=2, signed=True),
            col("year_ago", "1년 전", decimals=2),
            col("change_y", "1년 대비", decimals=2, signed=True),
            col("status", "상태"),
        ],
        "rows": rows,
        "checks": [
            {"col": "change", "op": "diff", "a": "latest", "b": "previous"},
            {"col": "change_y", "op": "diff", "a": "latest", "b": "year_ago"},
        ],
        "footnote": "ECB BSI(매각·증권화 조정 대출)·MIR(신규취급 복합 차입비용)",
        "sources": ["ECB Data Portal"],
    }


# ---------------------------------------------------------------------------
# (h) 재정
# ---------------------------------------------------------------------------
def t_fiscal(store) -> dict:
    rows = []
    for g in GEOS:
        gl = g.lower()
        d = store["series"].get(f"{gl}_deficit")
        q = store["series"].get(f"{gl}_debt_q")
        dl = last_valid(d["points"]) if d else None
        ql = last_valid(q["points"]) if q else None
        d_prev = _prev_valid(d["points"], dl[0]) if dl else None
        q_ya = (
            _val_at(store, f"{gl}_debt_q", f"{int(ql[0][:4]) - 1}{ql[0][4:]}")
            if ql
            else None
        )
        rows.append(
            {
                "geo": GEO_KO[g],
                "deficit_year": dl[0] if dl else None,
                "deficit": dl[1] if dl else None,
                "deficit_prev": d_prev[1] if d_prev else None,
                "deficit_chg": _diff(
                    dl[1] if dl else None, d_prev[1] if d_prev else None
                ),
                "debt_q": ql[0] if ql else None,
                "debt": ql[1] if ql else None,
                "debt_year_ago": q_ya,
                "debt_chg_y": _diff(ql[1] if ql else None, q_ya),
            }
        )
    return {
        "id": "fiscal",
        "section": "fiscal",
        "order": 1,
        "title": "재정수지·정부부채 (GDP 대비)",
        "subtitle": "재정수지는 연간(EDP 통보), 부채는 분기",
        "columns": [
            col("geo", "국가", bold=True),
            col("deficit_year", "연도"),
            col("deficit", "재정수지", "% GDP", 1, signed=True, bold=True),
            col("deficit_prev", "전년", "% GDP", 1, signed=True),
            col("deficit_chg", "변화", "%p", 1, signed=True),
            col("debt_q", "분기"),
            col("debt", "정부부채", "% GDP", 1, bold=True),
            col("debt_year_ago", "1년 전", "% GDP", 1),
            col("debt_chg_y", "1년 변화", "%p", 1, signed=True),
        ],
        "rows": rows,
        "checks": [
            {"col": "deficit_chg", "op": "diff", "a": "deficit", "b": "deficit_prev"},
            {"col": "debt_chg_y", "op": "diff", "a": "debt", "b": "debt_year_ago"},
        ],
        "footnote": "Eurostat gov_10dd_edpt1(재정수지 B9)·gov_10q_ggdebt(통합 총부채)",
        "sources": ["Eurostat"],
    }


# ---------------------------------------------------------------------------
# (i) 국가별 GDP 최근 4개 분기
# ---------------------------------------------------------------------------
def t_gdp_quarters(store) -> dict:
    ea = store["series"].get("ea_gdp_qoq")
    lv = last_valid(ea["points"]) if ea else None
    if not lv:
        return {}
    qi = period_index("Q", lv[0])
    qs = [f"{(i) // 4}-Q{i % 4 + 1}" for i in range(qi - 3, qi + 1)]
    rows = []
    for g in GEOS:
        r = {"geo": GEO_KO[g]}
        for q in qs:
            r[q] = _val_at(store, f"{g.lower()}_gdp_qoq", q)
        r["yoy"] = _val_at(store, f"{g.lower()}_gdp_yoy", qs[-1])
        rows.append(r)
    cols = [col("geo", "국가", bold=True)]
    cols += [col(q, period_ko(q), "% QoQ", 1, signed=True) for q in qs]
    cols.append(col("yoy", f"전년동기비 {period_ko(qs[-1])}", "% YoY", 1, signed=True))
    return {
        "id": "gdp_quarters",
        "section": "growth",
        "order": 2,
        "title": "국가별 실질 GDP — 최근 4개 분기",
        "subtitle": "계절·역일조정 전기비, Eurostat 최신 추계",
        "columns": cols,
        "rows": rows,
        "checks": [],
        "footnote": "Eurostat namq_10_gdp(CLV_PCH_PRE·CLV_PCH_SM). "
        "최신 분기는 개정 가능",
        "sources": ["Eurostat"],
    }


def _header(c: dict) -> str:
    u = c["unit"]
    return f"{c['label']} ({u})" if u and u not in c["label"] else c["label"]


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def to_markdown(t: dict) -> str:
    """표 1개 → 마크다운(제목·부제·표·자료 각주)."""
    cols = t["columns"]
    lines = [f"### {t['title']}", ""]
    if t.get("subtitle"):
        lines += [f"- {t['subtitle']}", ""]
    lines.append("| " + " | ".join(_header(c) for c in cols) + " |")
    aligns = [
        "---:" if any(_is_num(r.get(c["key"])) for r in t["rows"]) else "---"
        for c in cols
    ]
    lines.append("|" + "|".join(aligns) + "|")
    for r in t["rows"]:
        cells = []
        for c in cols:
            v = r.get(c["key"])
            dec = r.get("_decimals", {}).get(c["key"], c["decimals"])
            if _is_num(v):
                cell = fmt(v, dec, c["signed"])
            elif v is None:
                cell = "–"
            else:
                cell = str(v)
            if c["bold"] and cell != "–":
                cell = f"**{cell}**"
            cells.append(cell)
        lines.append("| " + " | ".join(cells) + " |")
    src = ", ".join(t.get("sources", []))
    lines += ["", f"자료: {src}. {t.get('footnote', '')}", ""]
    return "\n".join(lines)


def build(root: Path) -> dict:
    root = Path(root)
    store = load_store(root)
    ed_path = root / "edition.json"
    edition = (
        json.loads(ed_path.read_text(encoding="utf-8")) if ed_path.exists() else {}
    )
    month = edition.get("month") or store["as_of"][:7]
    as_of = store["as_of"]
    tables = [
        t_key_indicators(store),
        t_country_matrix(store),
        t_gdp_quarters(store),
        t_rates_fx(store),
        t_hicp(store),
        t_market_returns(store, month, as_of),
        t_ecb_history(store, edition),
        t_credit(store),
        t_fiscal(store),
    ]
    tables = [t for t in tables if t and t.get("rows")]
    doc = {
        "version": VERSION,
        "as_of": as_of,
        "month": month,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tables": tables,
    }
    data = root / "data"
    (data / "table_pack.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    md = [f"# 부록 표 — {period_ko(month)} (기준일 {as_of})", ""]
    md += [to_markdown(t) for t in tables]
    (data / "tables.md").write_text("\n".join(md), encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="table_pack")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", required=True)
    a = ap.parse_args(argv)
    doc = build(Path(a.root))
    print(f"tables {len(doc['tables'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
