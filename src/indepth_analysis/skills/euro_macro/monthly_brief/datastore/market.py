"""시장 시계열 수집기 — yfinance 일별 종가 · FRED 무키 CSV · 로컬 캘린더 DB.

- yfinance: ``Close``(auto_adjust=False) 결측 제거 후 일별 ``spot``. 원시 응답은
  ``date,close`` CSV로 캐시(오프라인 재실행).
- FRED: ``https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>&cosd=<start>``;
  값 ``.``은 휴일 → 제외.
- local_db: optionsdeck ``macro_calendar_history``(읽기전용 스냅샷 어댑터) 실적치를
  참조월로 매핑. PMI: 발표일 15일 이후=당월 flash, 이전=전월 final.
  HICP: 제목에 Flash이면서 20일 이후=당월 flash, 그 외=전월(final 우선).
"""

from __future__ import annotations

import csv
import io
import urllib.request

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def _yf_csv(ticker: str, start: str) -> str:
    import yfinance as yf

    h = yf.Ticker(ticker).history(start=start, interval="1d", auto_adjust=False)
    buf = io.StringIO()
    buf.write("date,close\n")
    if h is not None and not h.empty:
        close = h["Close"].dropna()
        for d, v in zip(close.index, close.values, strict=True):
            buf.write(f"{d.strftime('%Y-%m-%d')},{float(v):.6f}\n")
    return buf.getvalue()


def fetch_yf(spec, ctx) -> dict:
    tk = spec.query["ticker"]
    text = ctx.cached_text(
        "yf", f"{tk}_{spec.start}", lambda: _yf_csv(tk, spec.start), ext="csv"
    )
    pts = []
    for row in csv.DictReader(io.StringIO(text)):
        v = float(row["close"])
        pts.append([row["date"], round(v, 4), "spot"])
    if not pts:
        raise RuntimeError(f"yfinance {tk}: 빈 응답")
    return {
        "points": pts,
        "url": f"https://finance.yahoo.com/quote/{tk}",
        "dataset": tk,
        "meta": {"ticker": tk},
    }


def fetch_fred(spec, ctx) -> dict:
    sid = spec.query["id"]
    params = [("id", sid), ("cosd", spec.start)]
    full = ctx.url(FRED, params)

    def _get() -> str:  # FRED는 httpx 요청을 지연시킴 → urllib + curl UA
        req = urllib.request.Request(full, headers={"User-Agent": "curl/8.7.1"})
        with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310
            return r.read().decode("utf-8")

    text = ctx.cached_text("fred", full, _get, ext="csv")
    pts = []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    for row in reader:
        if len(row) < 2 or row[1] in (".", ""):
            continue
        pts.append([row[0], float(row[1]), "spot"])
    return {"points": pts, "url": ctx.url(FRED, params), "dataset": sid, "meta": {}}


def _ref_month(release: str, kind: str, title: str) -> tuple[str, str]:
    y, m, d = int(release[:4]), int(release[5:7]), int(release[8:10])
    pm = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    cur = f"{y}-{m:02d}"
    if kind == "pmi":
        return (cur, "flash") if d >= 15 else (pm, "final")
    is_flash = "flash" in (title or "").lower()
    if is_flash:
        return (cur, "flash") if d >= 20 else (pm, "flash")
    return pm, "final"


def fetch_local(spec, ctx) -> dict:
    from indepth_analysis.data.optionsdeck_series import OptionsdeckSeriesClient

    sid, kind = spec.query["calendar_series"], spec.query["kind"]
    with OptionsdeckSeriesClient() as c:
        rows = c.get_calendar_history(series_id=sid, start=f"{spec.start[:7]}-01")
    by_period: dict[str, tuple[float, str]] = {}
    for r in rows:
        if r.actual_value is None:
            continue
        per, st = _ref_month(r.release_date, kind, r.event_title or "")
        prev = by_period.get(per)
        if prev is None or st == "final" or prev[1] != "final":
            by_period[per] = (float(r.actual_value), st)
    pts = [[p, v, st] for p, (v, st) in sorted(by_period.items())]
    return {
        "points": pts,
        "url": "optionsdeck macro.db:macro_calendar_history",
        "dataset": sid,
        "meta": {"n_releases": len(rows)},
    }


def next_releases(as_of: str) -> dict[str, str]:
    """로컬 캘린더의 향후 발표일 — ``{calendar_series_id: YYYY-MM-DD}`` (최초 1건)."""
    try:
        from indepth_analysis.data.optionsdeck_series import OptionsdeckSeriesClient

        with OptionsdeckSeriesClient() as c:
            rows = c.get_calendar_history(country="EU", start=as_of)
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    for r in rows:
        if r.actual_value is None and r.series_id not in out:
            out[r.series_id] = r.release_date[:10]
    return out
