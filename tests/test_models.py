from indepth_analysis.models.common import Signal, SignalWithConfidence


class TestSignal:
    def test_numeric_values(self):
        assert Signal.STRONG_BUY.numeric == 1.0
        assert Signal.NEUTRAL.numeric == 0.0
        assert Signal.STRONG_SELL.numeric == -1.0

    def test_from_score_strong_buy(self):
        assert Signal.from_score(0.9) == Signal.STRONG_BUY

    def test_from_score_buy(self):
        assert Signal.from_score(0.6) == Signal.BUY

    def test_from_score_neutral(self):
        assert Signal.from_score(0.0) == Signal.NEUTRAL

    def test_from_score_sell(self):
        assert Signal.from_score(-0.7) == Signal.SELL

    def test_from_score_strong_sell(self):
        assert Signal.from_score(-0.9) == Signal.STRONG_SELL


class TestSignalWithConfidence:
    def test_weighted_score(self):
        s = SignalWithConfidence(signal=Signal.BUY, confidence=0.8, rationale="test")
        assert abs(s.weighted_score - 0.67 * 0.8) < 0.01

    def test_neutral_weighted_score(self):
        s = SignalWithConfidence(signal=Signal.NEUTRAL, confidence=1.0)
        assert s.weighted_score == 0.0
