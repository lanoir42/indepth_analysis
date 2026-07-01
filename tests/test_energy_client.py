"""Smoke tests for EnergyClient (network-free via monkeypatched history)."""

import pandas as pd

from indepth_analysis.data import energy_client
from indepth_analysis.data.energy_client import EnergyClient, _guess_unit


class _FakeYF:
    def __init__(self, ticker: str) -> None:
        self.ticker = ticker

    def get_history(self, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        idx = pd.date_range("2025-01-01", periods=120, freq="D")
        return pd.DataFrame({"Close": [50.0 + i * 0.5 for i in range(120)]}, index=idx)


class _EmptyYF:
    def __init__(self, ticker: str) -> None:
        self.ticker = ticker

    def get_history(self, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        return pd.DataFrame()


def test_guess_unit():
    assert _guess_unit("brent_usd_bbl") == "USD/bbl"
    assert _guess_unit("ttf_gas_eur_mwh") == "EUR/MWh"
    assert _guess_unit("eur_usd") == "FX rate"
    assert _guess_unit("stoxx600") == "index"


def test_get_series_shape(monkeypatch):
    monkeypatch.setattr(energy_client, "YFinanceClient", _FakeYF)
    rec = EnergyClient().get_series("brent_usd_bbl", "BZ=F", period="6mo")
    assert rec["name"] == "brent_usd_bbl"
    assert rec["source"] == "yfinance"
    assert rec["unit"] == "USD/bbl"
    assert rec["latest"] == 50.0 + 119 * 0.5
    assert rec["period_start"] == 50.0
    assert rec["pct_change"] is not None
    # month-end sampled: 120 daily points spanning ~4 months -> a few points
    assert 3 <= len(rec["values"]) <= 6
    assert all("period" in v and "value" in v for v in rec["values"])


def test_get_series_empty_degrades(monkeypatch):
    monkeypatch.setattr(energy_client, "YFinanceClient", _EmptyYF)
    rec = EnergyClient().get_series("ttf_gas_eur_mwh", "TTF=F")
    assert rec["values"] == []
    assert rec["latest"] is None
    # never raises, always well-formed
    assert rec["name"] == "ttf_gas_eur_mwh"


def test_fetch_group_never_aborts(monkeypatch):
    monkeypatch.setattr(energy_client, "YFinanceClient", _FakeYF)
    out = EnergyClient().fetch_group({"a": "A=F", "b": "B=F"}, period="6mo")
    assert len(out) == 2
    assert {r["name"] for r in out} == {"a", "b"}
