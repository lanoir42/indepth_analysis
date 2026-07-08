"""Energy, commodity, European equity-index and FX price client.

Fills the structured-data gap for the euro-macro H1/H2 report: energy prices
(oil, gas), European equity indices (STOXX600 etc.) and EUR crosses. Keyless,
built on yfinance via the existing YFinanceClient wrapper.

Honesty principle: only series with a real free source are exposed here. Some
targets (EUA carbon spot, German baseload power) have no reliable free
structured feed and are left to the web-research team to source with citations;
they are simply absent from this client's output rather than faked.
"""

import logging
from datetime import date

import pandas as pd

from .yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)

# yfinance tickers. Energy/commodity futures (front month, continuous).
ENERGY_TICKERS: dict[str, str] = {
    "brent_usd_bbl": "BZ=F",  # ICE Brent crude
    "wti_usd_bbl": "CL=F",  # NYMEX WTI crude
    "ttf_gas_eur_mwh": "TTF=F",  # Dutch TTF natural gas (best-effort)
    "henry_hub_usd_mmbtu": "NG=F",  # US Henry Hub (context / spread)
}

# European (and UK) headline equity indices + EU bank sector proxy.
INDEX_TICKERS: dict[str, str] = {
    "stoxx600": "^STOXX",  # STOXX Europe 600
    "euro_stoxx_50": "^STOXX50E",
    "dax": "^GDAXI",  # Germany
    "cac40": "^FCHI",  # France
    "ftse_mib": "FTSEMIB.MI",  # Italy
    "ibex35": "^IBEX",  # Spain
    "ftse100": "^FTSE",  # UK
}

# EUR crosses (yahoo FX). ECB/frankfurter is primary in ecb_client; these give
# daily granularity + period stats for the report's market section.
FX_TICKERS: dict[str, str] = {
    "eur_usd": "EURUSD=X",
    "eur_gbp": "EURGBP=X",
    "eur_jpy": "EURJPY=X",
}

# European AI / semiconductor / electrification basket for the H2 report's AI
# axis (data-centre build-out physically ties AI capex to power demand -> the
# energy axis). NVDA is a US benchmark for relative-strength context, not a
# European name. Prices via yfinance; degrade silently per ticker.
AI_BASKET_TICKERS: dict[str, str] = {
    "asml": "ASML.AS",  # lithography — Europe's AI-supply-chain keystone
    "sap": "SAP.DE",  # enterprise software / applied AI
    "siemens": "SIE.DE",  # industrial automation
    "siemens_energy": "ENR.DE",  # grid / power kit for data centres
    "schneider": "SU.PA",  # data-centre power & cooling
    "legrand": "LR.PA",  # data-centre electrical infrastructure
    "infineon": "IFX.DE",  # power semiconductors
    "stmicro": "STMPA.PA",  # semiconductors
    "nvidia_benchmark": "NVDA",  # US AI benchmark (context only)
}

# Human labels for metadata / report tables.
SERIES_LABELS: dict[str, str] = {
    "brent_usd_bbl": "Brent crude (USD/bbl)",
    "wti_usd_bbl": "WTI crude (USD/bbl)",
    "ttf_gas_eur_mwh": "Dutch TTF natural gas (EUR/MWh)",
    "henry_hub_usd_mmbtu": "Henry Hub gas (USD/MMBtu)",
    "stoxx600": "STOXX Europe 600",
    "euro_stoxx_50": "Euro STOXX 50",
    "dax": "DAX (Germany)",
    "cac40": "CAC 40 (France)",
    "ftse_mib": "FTSE MIB (Italy)",
    "ibex35": "IBEX 35 (Spain)",
    "ftse100": "FTSE 100 (UK)",
    "eur_usd": "EUR/USD",
    "eur_gbp": "EUR/GBP",
    "eur_jpy": "EUR/JPY",
    "asml": "ASML (NL)",
    "sap": "SAP (DE)",
    "siemens": "Siemens (DE)",
    "siemens_energy": "Siemens Energy (DE)",
    "schneider": "Schneider Electric (FR)",
    "legrand": "Legrand (FR)",
    "infineon": "Infineon (DE)",
    "stmicro": "STMicroelectronics",
    "nvidia_benchmark": "NVIDIA (US benchmark)",
}


class EnergyClient:
    """Keyless energy / commodity / European index / FX price client."""

    def get_series(
        self,
        name: str,
        ticker: str,
        period: str = "1y",
    ) -> dict:
        """Fetch one price series and summarise it for the report backbone.

        Returns a dict with period stats and a month-end sampled history
        (compact enough for a data.json chart series). On any failure returns
        an empty-but-well-formed record (values=[]) so the pipeline continues.
        """
        record: dict = {
            "name": name,
            "label": SERIES_LABELS.get(name, name),
            "source": "yfinance",
            "series_id": ticker,
            "as_of": date.today().isoformat(),
        }
        df = YFinanceClient(ticker).get_history(period=period, interval="1d")
        if df is None or df.empty or "Close" not in df.columns:
            logger.warning("No history for %s (%s)", name, ticker)
            record.update({"unit": None, "latest": None, "values": []})
            return record

        close = df["Close"].dropna()
        if close.empty:
            record.update({"unit": None, "latest": None, "values": []})
            return record

        latest = float(close.iloc[-1])
        first = float(close.iloc[0])
        latest_dt = close.index[-1]
        first_dt = close.index[0]

        # Month-end sampled series for compact charting.
        monthly = close.resample("ME").last().dropna()
        values = [
            {"period": idx.strftime("%Y-%m"), "value": round(float(v), 4)}
            for idx, v in monthly.items()
        ]

        record.update(
            {
                "unit": _guess_unit(name),
                "latest": round(latest, 4),
                "latest_date": _fmt_date(latest_dt),
                "period_start": round(first, 4),
                "period_start_date": _fmt_date(first_dt),
                "pct_change": round((latest / first - 1) * 100, 2) if first else None,
                "high": round(float(close.max()), 4),
                "low": round(float(close.min()), 4),
                "n_points": int(close.shape[0]),
                "values": values,
            }
        )
        return record

    def fetch_group(
        self,
        tickers: dict[str, str],
        period: str = "1y",
    ) -> list[dict]:
        """Fetch a named group of series (energy / index / fx)."""
        out: list[dict] = []
        for name, ticker in tickers.items():
            try:
                out.append(self.get_series(name, ticker, period=period))
            except Exception as e:  # noqa: BLE001 - never abort the batch
                logger.warning("Failed series %s (%s): %s", name, ticker, e)
                out.append(
                    {
                        "name": name,
                        "label": SERIES_LABELS.get(name, name),
                        "source": "yfinance",
                        "series_id": ticker,
                        "as_of": date.today().isoformat(),
                        "unit": None,
                        "latest": None,
                        "values": [],
                        "error": str(e),
                    }
                )
        return out

    def fetch_all(self, period: str = "1y") -> dict[str, list[dict]]:
        """Fetch energy, indices, FX and AI-basket groups. Empties degrade."""
        return {
            "energy": self.fetch_group(ENERGY_TICKERS, period=period),
            "indices": self.fetch_group(INDEX_TICKERS, period=period),
            "fx": self.fetch_group(FX_TICKERS, period=period),
            "ai_basket": self.fetch_group(AI_BASKET_TICKERS, period=period),
        }


def _guess_unit(name: str) -> str | None:
    if name.endswith("_usd_bbl"):
        return "USD/bbl"
    if name.endswith("_eur_mwh"):
        return "EUR/MWh"
    if name.endswith("_usd_mmbtu"):
        return "USD/MMBtu"
    if name.startswith("eur_"):
        return "FX rate"
    return "index"


def _fmt_date(idx) -> str:  # noqa: ANN001 - pandas Timestamp
    try:
        return pd.Timestamp(idx).date().isoformat()
    except Exception:  # noqa: BLE001
        return str(idx)
