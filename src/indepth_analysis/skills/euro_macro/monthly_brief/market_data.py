"""시장 시계열(결정론) — yfinance 일별·월말 + ECB Data Portal 월별 국채 10y.

    M=indepth_analysis.skills.euro_macro.monthly_brief.market_data
    uv run python -m $M --root reports/euro_macro/monthly_brief/2026-08 \
        --start 2024-01-01

산출 ``{root}/data/series_S4_market_local.json`` — Sonnet S3 수집의 공백
(월말 지수·국채·스프레드)을 로컬 API로 보강.
은행·자동차 섹터는 ETF 프록시(EXV1.DE·EXV5.DE)로 라벨 명시.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import requests

YF_TICKERS: dict[str, tuple[str, str]] = {
    "stoxx600": ("^STOXX", "STOXX Europe 600"),
    "eurostoxx50": ("^STOXX50E", "Euro STOXX 50"),
    "dax": ("^GDAXI", "DAX"),
    "cac40": ("^FCHI", "CAC 40"),
    "ftsemib": ("FTSEMIB.MI", "FTSE MIB"),
    "ibex35": ("^IBEX", "IBEX 35"),
    "eurusd": ("EURUSD=X", "EUR/USD"),
    "eurgbp": ("EURGBP=X", "EUR/GBP"),
    "eurjpy": ("EURJPY=X", "EUR/JPY"),
    "brent_usd": ("BZ=F", "Brent 선물 ($/bbl)"),
    "ttf_gas_eur_mwh": ("TTF=F", "Dutch TTF 천연가스 선물 (€/MWh)"),
    "banks_proxy_exv1": ("EXV1.DE", "iShares STOXX Europe 600 Banks ETF (프록시)"),
    "autos_proxy_exv5": (
        "EXV5.DE",
        "iShares STOXX Europe 600 Automobiles ETF (프록시)",
    ),
    "us_10y": ("^TNX", "US 10y yield (%)"),
}
ECB_10Y = {"DE": "독일", "FR": "프랑스", "IT": "이탈리아", "ES": "스페인"}


def _yf_series(ticker: str, start: str) -> tuple[list[str], list[float | None]]:
    import yfinance as yf

    h = yf.Ticker(ticker).history(start=start, interval="1d", auto_adjust=False)
    if h is None or h.empty:
        return [], []
    close = h["Close"].dropna()
    return [d.strftime("%Y-%m-%d") for d in close.index], [
        round(float(v), 4) for v in close.values
    ]


def _month_end(labels: list[str], values: list[float | None]) -> tuple[list[str], list]:
    last: dict[str, float | None] = {}
    for d, v in zip(labels, values, strict=True):
        last[d[:7]] = v  # 오름차순이므로 마지막 관측이 월말
    return list(last.keys()), list(last.values())


def _ecb_10y(cc: str, start_period: str) -> tuple[list[str], list[float | None]]:
    url = (
        "https://data-api.ecb.europa.eu/service/data/IRS/"
        f"M.{cc}.L.L40.CI.0000.EUR.N.Z?startPeriod={start_period}&format=jsondata"
    )
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    j = r.json()
    obs_dim = j["structure"]["dimensions"]["observation"][0]["values"]
    labels = [v["id"] for v in obs_dim]
    series = next(iter(j["dataSets"][0]["series"].values()))["observations"]
    vals: list[float | None] = [None] * len(labels)
    for idx, v in series.items():
        vals[int(idx)] = round(float(v[0]), 3) if v and v[0] is not None else None
    return labels, vals


def build(start: str, as_of: str) -> dict:
    out: dict = {"as_of": as_of, "series": {}, "unresolved": []}
    for key, (tk, title) in YF_TICKERS.items():
        try:
            lab, val = _yf_series(tk, start)
        except Exception as exc:  # noqa: BLE001
            out["unresolved"].append(f"{key}: {exc}")
            continue
        if not lab:
            out["unresolved"].append(f"{key} ({tk}): no data")
            continue
        out["series"][f"{key}_daily"] = {
            "title": title,
            "unit": "level",
            "frequency": "D",
            "x_labels": lab,
            "data": val,
            "source": f"Yahoo Finance via yfinance ({tk})",
            "published": lab[-1],
        }
        ml, mv = _month_end(lab, val)
        out["series"][f"{key}_monthly"] = {
            "title": f"{title} (월말)",
            "unit": "level",
            "frequency": "M",
            "x_labels": ml,
            "data": mv,
            "source": f"Yahoo Finance via yfinance ({tk}), 월중 마지막 종가",
            "published": lab[-1],
        }
    yields: dict[str, tuple[list[str], list]] = {}
    for cc, name in ECB_10Y.items():
        try:
            lab, val = _ecb_10y(cc, start[:7])
        except Exception as exc:  # noqa: BLE001
            out["unresolved"].append(f"ecb_10y_{cc}: {exc}")
            continue
        yields[cc] = (lab, val)
        out["series"][f"{cc.lower()}_gov10y_monthly"] = {
            "title": f"{name} 10년 국채수익률 (월평균, %)",
            "unit": "%",
            "frequency": "M",
            "x_labels": lab,
            "data": val,
            "source": f"ECB Data Portal IRS.M.{cc}.L.L40.CI.0000.EUR.N.Z",
            "published": lab[-1] if lab else None,
        }
    if "DE" in yields:
        dl, dv = yields["DE"]
        for cc, nm in (("FR", "OAT"), ("IT", "BTP"), ("ES", "Bonos")):
            if cc not in yields:
                continue
            cl, cv = yields[cc]
            common = [m for m in dl if m in cl]
            spread = []
            for m in common:
                a, b = cv[cl.index(m)], dv[dl.index(m)]
                spread.append(
                    round((a - b) * 100, 1) if a is not None and b is not None else None
                )
            out["series"][f"{nm.lower()}_bund_spread_bp_monthly"] = {
                "title": f"{nm}-Bund 10y 스프레드 (월평균, bp)",
                "unit": "bp",
                "frequency": "M",
                "x_labels": common,
                "data": spread,
                "source": "ECB Data Portal IRS 월평균 차이 (검산: (해당국 − DE) × 100)",
                "published": common[-1] if common else None,
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--as-of", default=date.today().isoformat())
    a = ap.parse_args()
    root = Path(a.root)
    (root / "data").mkdir(parents=True, exist_ok=True)
    d = build(a.start, a.as_of)
    dest = root / "data" / "series_S4_market_local.json"
    dest.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in d["series"].items():
        print(k, len(v["x_labels"]), v["x_labels"][-1:], v["data"][-1:])
    print("unresolved:", d["unresolved"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
