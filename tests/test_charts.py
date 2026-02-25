import numpy as np
import pandas as pd

from indepth_analysis.models.report_data import (
    FundamentalsHistory,
    IndicatorSeries,
    ReportData,
)
from indepth_analysis.output.charts import (
    generate_all_charts,
    generate_fundamentals_chart,
    generate_macd_chart,
    generate_price_chart,
    generate_rsi_chart,
)


def _make_report_data(n: int = 252) -> ReportData:
    dates = pd.bdate_range(end="2025-12-31", periods=n)
    np.random.seed(42)
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + np.random.normal(0.001, 0.02)))
    close = pd.Series(prices, index=dates)

    return ReportData(
        indicators=IndicatorSeries(
            dates=dates,
            close=close,
            sma_20=close.rolling(20).mean(),
            sma_50=close.rolling(50).mean(),
            sma_200=close.rolling(200).mean(),
            rsi_14=pd.Series(np.random.uniform(20, 80, n), index=dates),
            macd_line=pd.Series(np.random.normal(0, 1, n), index=dates),
            macd_signal=pd.Series(np.random.normal(0, 0.8, n), index=dates),
            macd_histogram=pd.Series(np.random.normal(0, 0.5, n), index=dates),
            volume=pd.Series(np.random.randint(1_000_000, 10_000_000, n), index=dates),
        ),
        fundamentals_history=FundamentalsHistory(
            dates=["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"],
            revenue=[50e9, 52e9, 55e9, 58e9],
            net_income=[15e9, 16e9, 17e9, 18e9],
            gross_margin=[68.0, 69.0, 69.5, 70.0],
            operating_margin=[42.0, 43.0, 44.0, 44.5],
            profit_margin=[30.0, 30.8, 30.9, 31.0],
        ),
    )


class TestChartGeneration:
    def test_generate_price_chart(self, tmp_path):
        rd = _make_report_data()
        path = generate_price_chart(rd, "MSFT", tmp_path)
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"
        assert "MSFT_price" in path.name

    def test_generate_rsi_chart(self, tmp_path):
        rd = _make_report_data()
        path = generate_rsi_chart(rd, "MSFT", tmp_path)
        assert path is not None
        assert path.exists()
        assert "MSFT_rsi" in path.name

    def test_generate_macd_chart(self, tmp_path):
        rd = _make_report_data()
        path = generate_macd_chart(rd, "MSFT", tmp_path)
        assert path is not None
        assert path.exists()
        assert "MSFT_macd" in path.name

    def test_generate_fundamentals_chart(self, tmp_path):
        rd = _make_report_data()
        path = generate_fundamentals_chart(rd, "MSFT", tmp_path)
        assert path is not None
        assert path.exists()
        assert "MSFT_fundamentals" in path.name

    def test_generate_all_charts(self, tmp_path):
        rd = _make_report_data()
        charts = generate_all_charts(rd, "MSFT", tmp_path)
        assert "price" in charts
        assert "rsi" in charts
        assert "macd" in charts
        assert "fundamentals" in charts
        assert all(p.exists() for p in charts.values())

    def test_empty_indicators_returns_none(self, tmp_path):
        rd = ReportData()
        path = generate_price_chart(rd, "MSFT", tmp_path)
        assert path is None

    def test_partial_data_doesnt_crash(self, tmp_path):
        rd = ReportData(
            indicators=IndicatorSeries(
                dates=pd.bdate_range(end="2025-12-31", periods=10),
                close=pd.Series(range(10)),
            )
        )
        path = generate_price_chart(rd, "MSFT", tmp_path)
        assert path is not None or path is None  # just shouldn't crash

    def test_empty_fundamentals_returns_none(self, tmp_path):
        rd = ReportData()
        path = generate_fundamentals_chart(rd, "MSFT", tmp_path)
        assert path is None
