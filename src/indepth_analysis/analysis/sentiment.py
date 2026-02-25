import logging

import pandas as pd

from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.sentiment import SentimentData

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    def analyze(
        self,
        info: dict,
        recommendations: pd.DataFrame,
        current_price: float | None,
    ) -> tuple[SentimentData, SignalWithConfidence]:
        target_mean = info.get("targetMeanPrice")
        target_median = info.get("targetMedianPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        rec = info.get("recommendationKey", "N/A")

        buy = info.get("numberOfAnalystOpinions", 0)
        hold = 0
        sell = 0
        total = buy

        if not recommendations.empty:
            buy, hold, sell, total = self._count_ratings(recommendations)

        upside = None
        if target_mean and current_price and current_price > 0:
            upside = ((target_mean / current_price) - 1) * 100

        data = SentimentData(
            analyst_count=total,
            buy_count=buy,
            hold_count=hold,
            sell_count=sell,
            mean_target=target_mean,
            median_target=target_median,
            high_target=target_high,
            low_target=target_low,
            current_price=current_price,
            upside_pct=upside,
            recommendation=rec,
        )

        signal = self._score(data)
        return data, signal

    def _count_ratings(self, df: pd.DataFrame) -> tuple[int, int, int, int]:
        buy = 0
        hold = 0
        sell = 0

        if df.empty:
            return 0, 0, 0, 0

        for col in df.columns:
            col_lower = col.lower()
            if col_lower in (
                "strongbuy",
                "buy",
                "strong_buy",
            ):
                buy += int(df[col].sum())
            elif col_lower in ("hold", "neutral"):
                hold += int(df[col].sum())
            elif col_lower in (
                "sell",
                "strongsell",
                "strong_sell",
                "underperform",
            ):
                sell += int(df[col].sum())

        total = buy + hold + sell
        return buy, hold, sell, total

    def _score(self, data: SentimentData) -> SignalWithConfidence:
        scores: list[float] = []
        reasons: list[str] = []

        if data.upside_pct is not None:
            if data.upside_pct > 20:
                scores.append(0.7)
                reasons.append("Large upside to target")
            elif data.upside_pct > 10:
                scores.append(0.4)
                reasons.append("Moderate upside")
            elif data.upside_pct > 0:
                scores.append(0.1)
                reasons.append("Slight upside")
            elif data.upside_pct > -10:
                scores.append(-0.2)
                reasons.append("Near target")
            else:
                scores.append(-0.5)
                reasons.append("Above analyst targets")

        total = data.buy_count + data.hold_count + data.sell_count
        if total > 0:
            buy_pct = data.buy_count / total
            sell_pct = data.sell_count / total
            if buy_pct > 0.7:
                scores.append(0.5)
                reasons.append("Strong analyst consensus buy")
            elif buy_pct > 0.5:
                scores.append(0.3)
                reasons.append("Majority buy ratings")
            elif sell_pct > 0.3:
                scores.append(-0.4)
                reasons.append("Significant sell ratings")
            else:
                scores.append(0.0)
                reasons.append("Mixed analyst opinions")

        rec = data.recommendation.lower()
        if rec in ("strong_buy", "strongbuy"):
            scores.append(0.5)
        elif rec == "buy":
            scores.append(0.3)
        elif rec == "hold":
            scores.append(0.0)
        elif rec in ("sell", "underperform"):
            scores.append(-0.4)

        if not scores:
            return SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.3,
                rationale="Limited sentiment data",
            )

        avg = sum(scores) / len(scores)
        confidence = min(0.7, len(scores) / 3.0 * 0.7)
        return SignalWithConfidence(
            signal=Signal.from_score(avg),
            confidence=round(confidence, 2),
            rationale="; ".join(reasons),
        )
