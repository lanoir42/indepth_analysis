from indepth_analysis.analysis.aggregator import InvestmentAggregator
from indepth_analysis.config import DEFAULT_WEIGHTS
from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.report import InvestmentReport


class TestAggregator:
    def test_all_buy_signals(self):
        report = InvestmentReport(ticker="TEST", company_name="Test Co")
        buy = SignalWithConfidence(signal=Signal.BUY, confidence=0.8, rationale="test")
        report.fundamental_signal = buy
        report.technical_signal = buy
        report.macro_signal = buy
        report.sentiment_signal = buy

        agg = InvestmentAggregator(DEFAULT_WEIGHTS)
        agg.aggregate(report)

        assert report.overall_signal in (Signal.BUY, Signal.STRONG_BUY, Signal.LEAN_BUY)
        assert report.overall_confidence > 0
        assert len(report.dimension_results) == 6

    def test_mixed_signals(self):
        report = InvestmentReport(ticker="TEST")
        report.fundamental_signal = SignalWithConfidence(
            signal=Signal.BUY, confidence=0.8
        )
        report.technical_signal = SignalWithConfidence(
            signal=Signal.SELL, confidence=0.7
        )
        report.macro_signal = SignalWithConfidence(
            signal=Signal.NEUTRAL, confidence=0.5
        )
        report.sentiment_signal = SignalWithConfidence(
            signal=Signal.LEAN_BUY, confidence=0.6
        )

        agg = InvestmentAggregator(DEFAULT_WEIGHTS)
        agg.aggregate(report)

        assert report.overall_signal is not None
        assert report.summary != ""

    def test_no_signals(self):
        report = InvestmentReport(ticker="TEST")
        agg = InvestmentAggregator(DEFAULT_WEIGHTS)
        agg.aggregate(report)

        assert report.overall_signal == Signal.NEUTRAL
        assert report.overall_confidence == 0.0

    def test_weight_redistribution(self):
        report = InvestmentReport(ticker="TEST")
        report.fundamental_signal = SignalWithConfidence(
            signal=Signal.BUY, confidence=0.8
        )

        agg = InvestmentAggregator(DEFAULT_WEIGHTS)
        agg.aggregate(report)

        avail = [d for d in report.dimension_results if d.available]
        assert len(avail) == 1
        assert avail[0].weight == 1.0

    def test_summary_includes_ticker(self):
        report = InvestmentReport(ticker="AAPL")
        report.fundamental_signal = SignalWithConfidence(
            signal=Signal.BUY, confidence=0.8
        )

        agg = InvestmentAggregator(DEFAULT_WEIGHTS)
        agg.aggregate(report)

        assert "AAPL" in report.summary
