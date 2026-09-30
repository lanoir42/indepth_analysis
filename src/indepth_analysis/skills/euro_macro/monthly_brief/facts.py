"""알려진 사실 블록 — ``ROOT/data/facts.json`` + ``ROOT/data/facts.md``.

    M=indepth_analysis.skills.euro_macro.monthly_brief.facts
    uv run python -m $M build --root reports/euro_macro/monthly_brief/2026-09

리서치 프롬프트·집필자에게 주입하는 결정론 수치 요약. 지표별 최신값·직전값·변화·
기간·상태·수집일·출처. 월·분기·연 계열의 직전값은 직전 비결측 기간, 일별 계열은
1개월 전(해당일 또는 직전 영업일) 관측.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .chart_pack import close_on_or_before, decision_dates, fmt, last_valid, period_ko
from .datastore.store import load_store
from .table_pack import _prev_valid, _shift, _status_ko

FACTS: list[tuple[str, str]] = [
    # (series id, 그룹)
    ("ea_hicp_headline", "물가"),
    ("ea_hicp_core", "물가"),
    ("ea_hicp_services", "물가"),
    ("ea_hicp_energy", "물가"),
    ("ea_hicp_food", "물가"),
    ("ea_hicp_neig", "물가"),
    ("ea_hicp_headline_mom", "물가"),
    ("de_hicp_headline", "물가"),
    ("fr_hicp_headline", "물가"),
    ("it_hicp_headline", "물가"),
    ("es_hicp_headline", "물가"),
    ("ea_gdp_qoq", "성장"),
    ("ea_gdp_yoy", "성장"),
    ("de_gdp_qoq", "성장"),
    ("fr_gdp_qoq", "성장"),
    ("it_gdp_qoq", "성장"),
    ("es_gdp_qoq", "성장"),
    ("ea_esi", "심리·실물"),
    ("ea_consumer_confidence", "심리·실물"),
    ("ea_industry_confidence", "심리·실물"),
    ("ea_ip_yoy", "심리·실물"),
    ("de_ip_yoy", "심리·실물"),
    ("ea_retail_yoy", "심리·실물"),
    ("ea_pmi_composite", "심리·실물"),
    ("ea_pmi_manufacturing", "심리·실물"),
    ("ea_pmi_services", "심리·실물"),
    ("ea_unemployment", "노동"),
    ("de_unemployment", "노동"),
    ("fr_unemployment", "노동"),
    ("it_unemployment", "노동"),
    ("es_unemployment", "노동"),
    ("ecb_dfr", "통화정책·금리"),
    ("ecb_mro", "통화정책·금리"),
    ("estr", "통화정책·금리"),
    ("de_bund_2y", "통화정책·금리"),
    ("de_bund_10y", "통화정책·금리"),
    ("fr_10y_m", "통화정책·금리"),
    ("it_10y_m", "통화정책·금리"),
    ("fr_spread_m", "통화정책·금리"),
    ("it_spread_m", "통화정책·금리"),
    ("es_spread_m", "통화정책·금리"),
    ("eurusd", "환율"),
    ("eurkrw", "환율"),
    ("eurgbp", "환율"),
    ("eurjpy", "환율"),
    ("stoxx600", "주식"),
    ("dax", "주식"),
    ("cac40", "주식"),
    ("ftsemib", "주식"),
    ("banks_proxy", "주식"),
    ("brent_dated", "에너지"),
    ("brent_fut", "에너지"),
    ("ttf", "에너지"),
    ("ea_loans_nfc", "신용"),
    ("ea_loans_hh", "신용"),
    ("ea_rate_nfc", "신용"),
    ("ea_rate_mortgage", "신용"),
    ("ea_deficit", "재정"),
    ("fr_deficit", "재정"),
    ("it_deficit", "재정"),
    ("fr_debt_q", "재정"),
    ("it_debt_q", "재정"),
]
PCT_UNITS = ("%", "% YoY", "% QoQ", "% MoM", "% of GDP")


def _chg_unit(unit: str, freq: str) -> str:
    if unit == "bp":
        return "bp"
    if unit in PCT_UNITS or unit.startswith("%"):
        return "%p"
    return "%" if freq == "D" else ""


def fact_for(store: dict, sid: str, group: str) -> dict | None:
    s = store["series"].get(sid)
    if not s:
        return None
    lv = last_valid(s["points"])
    if not lv:
        return None
    p, v, st = lv
    if s["freq"] == "D":
        ref = close_on_or_before(s["points"], _shift(p, 1))
        pv = (ref[0], ref[1], "") if ref else None
    else:
        pv = _prev_valid(s["points"], p)
    prev = pv[1] if pv else None
    cu = _chg_unit(s["unit"], s["freq"])
    if prev is None:
        chg = None
    elif cu == "%":
        chg = round((v / prev - 1) * 100, 2) if prev else None
    else:
        chg = round(v - prev, 4)
    return {
        "id": sid,
        "group": group,
        "title_ko": s["title_ko"],
        "unit": s["unit"],
        "freq": s["freq"],
        "period": p,
        "value": v,
        "prev_period": pv[0] if pv else None,
        "previous": prev,
        "change": chg,
        "change_unit": cu,
        "status": st,
        "tier": s["tier"],
        "source": s["source"],
        "dataset": s.get("dataset", ""),
        "fetched": (s.get("fetched") or "")[:10],
        "release_updated": (s.get("meta") or {}).get("updated", "")[:10],
        "decimals": s.get("decimals", 1),
    }


def _line(f: dict) -> str:
    d = f["decimals"]
    unit = f["unit"]
    val = fmt(f["value"], d)
    body = f"{f['title_ko']}: {val} {unit} ({period_ko(f['period'])}, "
    body += f"{_status_ko(f['status'])})"
    if f["previous"] is not None:
        cd = 2 if f["change_unit"] == "%" else d
        body += (
            f" — 직전 {fmt(f['previous'], d)} ({period_ko(f['prev_period'])}), "
            f"변화 {fmt(f['change'], cd, signed=True)}{f['change_unit']}"
        )
    src = f"{f['source']} {f['dataset']}".strip()
    rel = f", 갱신 {f['release_updated']}" if f["release_updated"] else ""
    tier = " [웹 수집]" if f["tier"] == "llm_web" else ""
    return f"- {body} · {src}{rel} · 수집 {f['fetched']}{tier}"


def build(root: Path) -> dict:
    root = Path(root)
    store = load_store(root)
    facts = [f for sid, g in FACTS if (f := fact_for(store, sid, g))]
    decisions = decision_dates(store)
    last_dec = decisions[-1] if decisions else None
    doc = {
        "as_of": store["as_of"],
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "facts": facts,
        "ecb_last_change": last_dec,
        "missing": [sid for sid, _ in FACTS if sid not in store["series"]],
        "store_errors": store.get("errors", {}),
    }
    data = root / "data"
    (data / "facts.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    md = [
        f"# 알려진 사실 — 결정론 데이터 (기준일 {store['as_of']})",
        "",
        "- 아래 수치는 공식 통계·시장 데이터에서 코드로 산출한 값. 본문 수치는 이 값을 "
        "우선 사용",
        "",
    ]
    if last_dec:
        md += [
            "## ECB 최근 금리 변경",
            "",
            f"- 결정 {last_dec['decision']} · 발효 {last_dec['effective']}: DFR "
            f"{fmt(last_dec['dfr'], 2)}% · MRO {fmt(last_dec['mro'], 2)}% · MLF "
            f"{fmt(last_dec['mlf'], 2)}% (DFR 변화 "
            f"{fmt(last_dec['dfr_chg_bp'], 0, signed=True)}bp)",
            "",
        ]
    group = None
    for f in facts:
        if f["group"] != group:
            group = f["group"]
            md += ["", f"## {group}", ""]
        md.append(_line(f))
    if doc["missing"]:
        md += ["", "## 미수집", "", "- " + ", ".join(doc["missing"])]
    (data / "facts.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="facts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", required=True)
    a = ap.parse_args(argv)
    doc = build(Path(a.root))
    print(f"facts {len(doc['facts'])} missing {len(doc['missing'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
