import numpy as np
import pandas as pd

from indepth_analysis.analysis.technical import TechnicalAnalyzer
from indepth_analysis.models.common import Signal


def make_history(n: int = 252, start: float = 100.0, trend: float = 0.001):
    dates = pd.bdate_range(end="2025-12-31", periods=n)
    np.random.seed(42)
    prices = [start]
    for _ in range(n - 1):
        change = np.random.normal(trend, 0.02)
        prices.append(prices[-1] * (1 + change))
    prices = np.array(prices)
    return pd.DataFrame(
        {
            "Open": prices * 0.999,
            "High": prices * 1.01,
            "Low": prices * 0.99,
            "Close": prices,
            "Volume": np.random.randint(1_000_000, 10_000_000, n),
        },
        index=dates,
    )


class TestTechnicalAnalyzer:
    def test_basic_analysis(self):
        analyzer = TechnicalAnalyzer()
        hist = make_history()
        data, signal, indicators = analyzer.analyze(hist, None)
        assert data.current_price is not None
        assert data.moving_averages.sma_20 is not None
        assert data.moving_averages.sma_50 is not None
        assert data.moving_averages.sma_200 is not None
        assert data.momentum.rsi_14 is not None
        assert signal.confidence > 0

    def test_short_history(self):
        analyzer = TechnicalAnalyzer()
        hist = make_history(n=10)
        data, signal, indicators = analyzer.analyze(hist, 100.0)
        assert signal.signal == Signal.NEUTRAL
        assert signal.confidence == 0.2

    def test_empty_history(self):
        analyzer = TechnicalAnalyzer()
        data, signal, indicators = analyzer.analyze(pd.DataFrame(), 100.0)
        assert signal.signal == Signal.NEUTRAL

    def test_uptrend_bullish(self):
        analyzer = TechnicalAnalyzer()
        hist = make_history(n=252, trend=0.005)
        data, signal, indicators = analyzer.analyze(hist, None)
        assert data.trend.above_200_sma is True
        assert data.trend.long_term_trend == "bullish"

    def test_support_resistance_detected(self):
        analyzer = TechnicalAnalyzer()
        hist = make_history(n=100)
        data, _, indicators = analyzer.analyze(hist, None)
        sr = data.support_resistance
        assert isinstance(sr.support_levels, list)
        assert isinstance(sr.resistance_levels, list)

    def test_indicator_series_populated(self):
        analyzer = TechnicalAnalyzer()
        hist = make_history()
        _, _, indicators = analyzer.analyze(hist, None)
        assert indicators.close is not None
        assert indicators.dates is not None
        assert indicators.sma_20 is not None
        assert indicators.rsi_14 is not None
        assert indicators.macd_line is not None
        assert indicators.macd_signal is not None
        assert indicators.macd_histogram is not None
        assert indicators.volume is not None
        assert len(indicators.close) == len(hist)

    def test_indicator_series_empty_on_short_history(self):
        analyzer = TechnicalAnalyzer()
        hist = make_history(n=10)
        _, _, indicators = analyzer.analyze(hist, 100.0)
        assert indicators.close is None
