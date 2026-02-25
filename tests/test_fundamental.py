import pandas as pd

from indepth_analysis.analysis.fundamental import FundamentalAnalyzer
from indepth_analysis.models.common import Signal


def make_info(**overrides):
    defaults = {
        "trailingPE": 25.0,
        "forwardPE": 22.0,
        "priceToBook": 10.0,
        "priceToSalesTrailing12Months": 12.0,
        "pegRatio": 1.5,
        "enterpriseToEbitda": 20.0,
        "marketCap": 3e12,
        "revenueGrowth": 0.15,
        "earningsGrowth": 0.10,
        "grossMargins": 0.69,
        "operatingMargins": 0.42,
        "profitMargins": 0.35,
        "currentRatio": 1.8,
        "debtToEquity": 40.0,
        "totalCash": 80e9,
        "totalDebt": 60e9,
    }
    defaults.update(overrides)
    return defaults


class TestFundamentalAnalyzer:
    def test_basic_analysis(self):
        analyzer = FundamentalAnalyzer()
        info = make_info()
        data, signal = analyzer.analyze(
            info, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert data.valuation.pe_ratio == 25.0
        assert data.valuation.market_cap == 3e12
        assert data.growth.revenue_growth_yoy == 15.0
        assert data.margins.gross_margin == 69.0
        assert signal.confidence > 0

    def test_low_pe_bullish(self):
        analyzer = FundamentalAnalyzer()
        info = make_info(trailingPE=10.0, pegRatio=0.8)
        data, signal = analyzer.analyze(
            info, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert signal.signal in (Signal.BUY, Signal.STRONG_BUY, Signal.LEAN_BUY)

    def test_high_pe_bearish(self):
        analyzer = FundamentalAnalyzer()
        info = make_info(
            trailingPE=50.0,
            pegRatio=3.0,
            revenueGrowth=-0.05,
            profitMargins=-0.1,
            debtToEquity=250.0,
        )
        data, signal = analyzer.analyze(
            info, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert signal.signal.numeric < 0

    def test_missing_data_returns_neutral(self):
        analyzer = FundamentalAnalyzer()
        data, signal = analyzer.analyze(
            {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert signal.signal == Signal.NEUTRAL
        assert signal.confidence == 0.2

    def test_debt_to_equity_scaled(self):
        analyzer = FundamentalAnalyzer()
        info = make_info(debtToEquity=80.0)
        data, _ = analyzer.analyze(info, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert data.balance_sheet.debt_to_equity == 0.8
