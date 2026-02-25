from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.report import DimensionResult, InvestmentReport


class InvestmentAggregator:
    def __init__(self, weights: dict[str, float]) -> None:
        self.base_weights = weights.copy()

    def aggregate(self, report: InvestmentReport) -> None:
        dimensions = [
            (
                "Fundamental",
                "fundamental",
                report.fundamental_signal,
            ),
            (
                "Technical",
                "technical",
                report.technical_signal,
            ),
            ("Options", "options", report.options_signal),
            ("Macro/Sector", "macro", report.macro_signal),
            (
                "Sentiment",
                "sentiment",
                report.sentiment_signal,
            ),
            (
                "Portfolio",
                "portfolio",
                report.portfolio_signal,
            ),
        ]

        available: list[tuple[str, str, SignalWithConfidence]] = []
        unavailable: list[tuple[str, str]] = []

        for name, key, sig in dimensions:
            if sig is not None:
                available.append((name, key, sig))
            else:
                unavailable.append((name, key))

        if not available:
            report.overall_signal = Signal.NEUTRAL
            report.overall_confidence = 0.0
            report.overall_score = 0.0
            report.summary = "No analysis dimensions available."
            return

        total_avail_weight = sum(
            self.base_weights.get(key, 0) for _, key, _ in available
        )

        results: list[DimensionResult] = []
        weighted_score = 0.0
        weighted_conf = 0.0

        for name, key, sig in available:
            base_w = self.base_weights.get(key, 0)
            adj_w = base_w / total_avail_weight if total_avail_weight > 0 else 0
            results.append(
                DimensionResult(
                    name=name,
                    weight=adj_w,
                    signal=sig,
                    available=True,
                )
            )
            weighted_score += sig.signal.numeric * adj_w
            weighted_conf += sig.confidence * adj_w

        for name, key in unavailable:
            neutral = SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.0,
                rationale="Not available",
            )
            results.append(
                DimensionResult(
                    name=name,
                    weight=self.base_weights.get(key, 0),
                    signal=neutral,
                    available=False,
                )
            )

        report.dimension_results = results
        report.overall_score = round(weighted_score, 4)
        report.overall_confidence = round(weighted_conf, 4)
        report.overall_signal = Signal.from_score(weighted_score)
        report.summary = self._build_summary(report)

    def _build_summary(self, report: InvestmentReport) -> str:
        sig = report.overall_signal
        ticker = report.ticker

        bull = [
            d
            for d in report.dimension_results
            if d.available and d.signal.signal.numeric > 0.2
        ]
        bear = [
            d
            for d in report.dimension_results
            if d.available and d.signal.signal.numeric < -0.2
        ]

        parts = [f"{ticker}: {sig.value}."]

        if bull:
            names = ", ".join(d.name for d in bull)
            parts.append(f"Bullish signals from {names}.")
        if bear:
            names = ", ".join(d.name for d in bear)
            parts.append(f"Bearish signals from {names}.")

        if not bull and not bear:
            parts.append("Mixed or neutral signals across all dimensions.")

        return " ".join(parts)
