"""백본 시드 — 로컬 DB에서 수치를 뽑아 JSON으로 고정.

소스: optionsdeck 스냅샷·macro_calendar.db.

    M=indepth_analysis.skills.euro_macro.monthly_brief.backbone
    uv run python -m $M --root reports/euro_macro/monthly_brief/2026-08 \
        --month 2026-08 --as-of 2026-09-10

LLM·네트워크 없음. optionsdeck DB는 어댑터 경유(읽기전용 스냅샷).
산출 ``{root}/data/backbone_seed.json``: 일별 Brent·WTI·VIX·DGS10·DFF
(대상월 -13개월~as_of), ECB 정책금리 결정 이력, FX 스냅샷, EU 캘린더.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

OD_SERIES = {
    "brent_usd": "DCOILBRENTEU",
    "wti_usd": "DCOILWTICO",
    "vix": "VIXCLS",
    "us_10y": "DGS10",
    "us_2y": "DGS2",
    "fed_funds_eff": "DFF",
    "ea_hicp_yoy_dbnomics": "M.RCH_A.CP00.EA",
}
CAL_DB = Path("data/macro_calendar.db")


def _od_client():
    try:
        from indepth_analysis.data.optionsdeck_series import OptionsdeckSeriesClient

        return OptionsdeckSeriesClient()
    except Exception as exc:  # noqa: BLE001
        print(f"optionsdeck 어댑터 불가: {exc}")
        return None


def _obs(client, series_id: str, start: str) -> list[dict]:
    rows: list[dict] = []
    # DBnomics 월별 계열은 기간 라벨이 YYYY-MM 형식(사전식 비교)
    st = start[:7] if series_id.startswith("M.") else start
    try:
        for r in client.get_series(series_id, start=st):
            rows.append({"date": r.date, "value": r.value})
    except Exception as exc:  # noqa: BLE001
        print(f"{series_id}: {exc}")
    return rows


def _ref_month(release_iso: str, title: str) -> str:
    """발표일·제목으로 참조월(YYYY-MM)을 추정.

    flash: 월말 발표 → 해당월(월초 1~3일 발표는 전월). final: 중순 발표 → 전월.
    """
    y, m, d = int(release_iso[:4]), int(release_iso[5:7]), int(release_iso[8:10])
    is_flash = "Flash" in title
    if is_flash and d >= 20:
        return f"{y}-{m:02d}"
    # 전월
    pm, py = (m - 1, y) if m > 1 else (12, y - 1)
    return f"{py}-{pm:02d}"


def eu_cpi_prints(conn: sqlite3.Connection, since: str) -> list[dict]:
    """로컬 캘린더 DB의 유로존 CPI 실적치(골든 체인 포함)를 참조월로 매핑."""
    rows = conn.execute(
        "select datetime_utc,title,actual,forecast,previous from calendar_events"
        " where country='EUR' and title like '%CPI%' and actual is not null"
        " and datetime_utc>=? order by datetime_utc",
        (since,),
    ).fetchall()
    out = []
    for dt, title, actual, fc, prev in rows:
        out.append(
            {
                "release_date": dt[:10],
                "title": title,
                "ref_month": _ref_month(dt, title),
                "measure": "core" if "Core" in title else "headline",
                "stage": "flash" if "Flash" in title else "final",
                "actual": actual,
                "forecast": fc,
                "previous": prev,
                "source": "macro_calendar.db calendar_events (FF/골든 체인)",
            }
        )
    return out


def build(root: Path, month: str, as_of: str) -> dict:
    y, m = (int(x) for x in month.split("-"))
    start = f"{y - 1 if m == 1 else y}-{(m - 1) or 12:02d}-01"
    start_long = f"{y - 1}-{m:02d}-01"
    out: dict = {"as_of": as_of, "month": month, "series": {}, "notes": []}
    client = _od_client()
    if client is not None:
        for key, sid in OD_SERIES.items():
            out["series"][key] = {
                "source_series": sid,
                "observations": _obs(client, sid, start_long),
            }
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    else:
        out["notes"].append("optionsdeck 스냅샷 없음 — 시리즈 생략")
    if CAL_DB.exists():
        c = sqlite3.connect(CAL_DB)
        out["ecb_rate_decisions"] = [
            dict(zip(("cb", "date", "rate", "prev", "change_bp"), r, strict=True))
            for r in c.execute(
                "select cb_name,date_utc,rate_pct,prev_rate,change_bp"
                " from rate_decisions where country='EUR'"
                " and (change_bp<>0 or date_utc>=?) order by date_utc",
                (start,),
            )
        ]
        out["fx_snapshot"] = [
            dict(zip(("date", "base", "quote", "rate"), r, strict=True))
            for r in c.execute(
                "select date_utc,base,quote,rate from fx_rates where base='EUR'"
                " order by date_utc desc limit 24"
            )
        ]
        out["eu_cpi_prints"] = eu_cpi_prints(c, f"{y - 1}-06-01")
        out["eu_calendar"] = [
            dict(
                zip(
                    ("datetime_utc", "title", "forecast", "previous", "actual"),
                    r,
                    strict=True,
                )
            )
            for r in c.execute(
                "select datetime_utc,title,forecast,previous,actual"
                " from calendar_events where country='EUR' and datetime_utc>=?"
                " order by datetime_utc",
                (f"{month}-01",),
            )
        ]
        c.close()
    else:
        out["notes"].append("data/macro_calendar.db 없음")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--month", required=True)
    ap.add_argument("--as-of", default=date.today().isoformat())
    a = ap.parse_args()
    root = Path(a.root)
    (root / "data").mkdir(parents=True, exist_ok=True)
    seed = build(root, a.month, a.as_of)
    dest = root / "data" / "backbone_seed.json"
    dest.write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {k: len(v.get("observations", [])) for k, v in seed["series"].items()}
    extra = {
        k: len(seed.get(k, []))
        for k in ("ecb_rate_decisions", "fx_snapshot", "eu_calendar", "eu_cpi_prints")
    }
    print(dest, summary, extra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
