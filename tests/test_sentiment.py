import pandas as pd

from indepth_analysis.analysis.sentiment import SentimentAnalyzer
from indepth_analysis.models.common import Signal


class TestSentimentAnalyzer:
    def test_bullish_sentiment(self):
        analyzer = SentimentAnalyzer()
        info = {
            "targetMeanPrice": 500.0,
            "targetMedianPrice": 490.0,
            "targetHighPrice": 600.0,
            "targetLowPrice": 400.0,
            "recommendationKey": "buy",
        }
        data, signal = analyzer.analyze(info, pd.DataFrame(), 400.0)
        assert data.upside_pct > 0
        assert signal.signal.numeric > 0

    def test_bearish_sentiment(self):
        analyzer = SentimentAnalyzer()
        info = {
            "targetMeanPrice": 300.0,
            "recommendationKey": "sell",
        }
        data, signal = analyzer.analyze(info, pd.DataFrame(), 400.0)
        assert data.upside_pct < 0
        assert signal.signal.numeric < 0

    def test_no_data(self):
        analyzer = SentimentAnalyzer()
        data, signal = analyzer.analyze({}, pd.DataFrame(), None)
        assert signal.signal == Signal.NEUTRAL

    def test_rating_counting(self):
        analyzer = SentimentAnalyzer()
        df = pd.DataFrame(
            {
                "strongBuy": [5],
                "buy": [10],
                "hold": [3],
                "sell": [2],
                "strongSell": [1],
            }
        )
        info = {
            "targetMeanPrice": 500.0,
            "recommendationKey": "buy",
        }
        data, _ = analyzer.analyze(info, df, 400.0)
        assert data.buy_count == 15
        assert data.hold_count == 3
        assert data.sell_count == 3
