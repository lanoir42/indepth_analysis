import logging

import numpy as np
import pandas as pd
import ta as ta_lib

from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.report_data import IndicatorSeries
from indepth_analysis.models.technical import (
    MomentumIndicators,
    MovingAverages,
    SupportResistance,
    TechnicalData,
    TrendAnalysis,
)

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    def analyze(
        self,
        history: pd.DataFrame,
        current_price: float | None,
    ) -> tuple[TechnicalData, SignalWithConfidence, IndicatorSeries]:
        if history.empty or len(history) < 20:
            return (
                TechnicalData(current_price=current_price),
                SignalWithConfidence(
                    signal=Signal.NEUTRAL,
                    confidence=0.2,
                    rationale="Insufficient price history",
                ),
                IndicatorSeries(),
            )

        close = history["Close"]
        if current_price is None:
            current_price = float(close.iloc[-1])

        ma = self._compute_moving_averages(close, current_price)
        mom = self._compute_momentum(history)
        sr = self._compute_support_resistance(close, current_price)
        trend = self._compute_trend(ma, close)

        data = TechnicalData(
            current_price=current_price,
            moving_averages=ma,
            momentum=mom,
            support_resistance=sr,
            trend=trend,
        )
        signal = self._score(data)
        indicators = self._build_indicator_series(history)
        return data, signal, indicators

    def _build_indicator_series(self, history: pd.DataFrame) -> IndicatorSeries:
        close = history["Close"]
        rsi = ta_lib.momentum.RSIIndicator(close, window=14)
        macd = ta_lib.trend.MACD(close)

        sma_20 = close.rolling(20).mean()
        sma_50 = close.rolling(50).mean() if len(close) >= 50 else None
        sma_200 = close.rolling(200).mean() if len(close) >= 200 else None

        volume = history["Volume"] if "Volume" in history.columns else None

        return IndicatorSeries(
            dates=history.index,
            close=close,
            sma_20=sma_20,
            sma_50=sma_50,
            sma_200=sma_200,
            rsi_14=rsi.rsi(),
            macd_line=macd.macd(),
            macd_signal=macd.macd_signal(),
            macd_histogram=macd.macd_diff(),
            volume=volume,
        )

    def _compute_moving_averages(
        self, close: pd.Series, price: float
    ) -> MovingAverages:
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        sma200 = (
            float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
        )
        ema12 = float(close.ewm(span=12).mean().iloc[-1])
        ema26 = float(close.ewm(span=26).mean().iloc[-1])

        def vs(sma: float | None) -> float | None:
            if sma is None or sma == 0:
                return None
            return ((price / sma) - 1) * 100

        return MovingAverages(
            sma_20=sma20,
            sma_50=sma50,
            sma_200=sma200,
            ema_12=ema12,
            ema_26=ema26,
            price_vs_sma20=vs(sma20),
            price_vs_sma50=vs(sma50),
            price_vs_sma200=vs(sma200),
        )

    def _compute_momentum(self, history: pd.DataFrame) -> MomentumIndicators:
        close = history["Close"]
        high = history["High"]
        low = history["Low"]

        rsi = ta_lib.momentum.RSIIndicator(close, window=14)
        macd = ta_lib.trend.MACD(close)
        stoch = ta_lib.momentum.StochasticOscillator(high, low, close)
        adx_ind = (
            ta_lib.trend.ADXIndicator(high, low, close) if len(history) >= 14 else None
        )

        return MomentumIndicators(
            rsi_14=_last_val(rsi.rsi()),
            macd=_last_val(macd.macd()),
            macd_signal=_last_val(macd.macd_signal()),
            macd_histogram=_last_val(macd.macd_diff()),
            stochastic_k=_last_val(stoch.stoch()),
            stochastic_d=_last_val(stoch.stoch_signal()),
            adx=_last_val(adx_ind.adx()) if adx_ind else None,
        )

    def _compute_support_resistance(
        self, close: pd.Series, price: float
    ) -> SupportResistance:
        recent = close.tail(60)
        if len(recent) < 10:
            return SupportResistance()

        local_min = recent[(recent.shift(1) > recent) & (recent.shift(-1) > recent)]
        local_max = recent[(recent.shift(1) < recent) & (recent.shift(-1) < recent)]

        supports = sorted(
            [float(v) for v in local_min if v < price],
            reverse=True,
        )
        resistances = sorted([float(v) for v in local_max if v > price])

        nearest_s = supports[0] if supports else None
        nearest_r = resistances[0] if resistances else None

        dist_s = ((price - nearest_s) / price * 100) if nearest_s else None
        dist_r = ((nearest_r - price) / price * 100) if nearest_r else None

        return SupportResistance(
            support_levels=supports[:5],
            resistance_levels=resistances[:5],
            nearest_support=nearest_s,
            nearest_resistance=nearest_r,
            distance_to_support_pct=dist_s,
            distance_to_resistance_pct=dist_r,
        )

    def _compute_trend(self, ma: MovingAverages, close: pd.Series) -> TrendAnalysis:
        price = float(close.iloc[-1])

        short = "neutral"
        if ma.sma_20 and price > ma.sma_20:
            short = "bullish"
        elif ma.sma_20 and price < ma.sma_20:
            short = "bearish"

        medium = "neutral"
        if ma.sma_50 and price > ma.sma_50:
            medium = "bullish"
        elif ma.sma_50 and price < ma.sma_50:
            medium = "bearish"

        long_t = "neutral"
        if ma.sma_200 and price > ma.sma_200:
            long_t = "bullish"
        elif ma.sma_200 and price < ma.sma_200:
            long_t = "bearish"

        golden = False
        death = False
        if ma.sma_50 is not None and ma.sma_200 is not None:
            sma50_series = close.rolling(50).mean()
            sma200_series = close.rolling(200).mean()
            if len(sma50_series.dropna()) >= 2:
                prev_diff = (
                    sma50_series.dropna().iloc[-2] - sma200_series.dropna().iloc[-2]
                )
                curr_diff = (
                    sma50_series.dropna().iloc[-1] - sma200_series.dropna().iloc[-1]
                )
                if prev_diff < 0 and curr_diff >= 0:
                    golden = True
                elif prev_diff > 0 and curr_diff <= 0:
                    death = True

        return TrendAnalysis(
            short_term_trend=short,
            medium_term_trend=medium,
            long_term_trend=long_t,
            golden_cross=golden,
            death_cross=death,
            above_200_sma=bool(ma.sma_200 and price > ma.sma_200),
        )

    def _score(self, data: TechnicalData) -> SignalWithConfidence:
        scores: list[float] = []
        reasons: list[str] = []

        mom = data.momentum
        if mom.rsi_14 is not None:
            if mom.rsi_14 < 30:
                scores.append(0.7)
                reasons.append("RSI oversold")
            elif mom.rsi_14 < 40:
                scores.append(0.3)
                reasons.append("RSI approaching oversold")
            elif mom.rsi_14 > 70:
                scores.append(-0.7)
                reasons.append("RSI overbought")
            elif mom.rsi_14 > 60:
                scores.append(-0.3)
                reasons.append("RSI approaching overbought")
            else:
                scores.append(0.1)
                reasons.append("RSI neutral")

        if mom.macd_histogram is not None:
            if mom.macd_histogram > 0:
                scores.append(0.4)
                reasons.append("MACD bullish")
            else:
                scores.append(-0.4)
                reasons.append("MACD bearish")

        t = data.trend
        trend_map = {
            "bullish": 0.3,
            "neutral": 0.0,
            "bearish": -0.3,
        }
        scores.append(trend_map.get(t.short_term_trend, 0))
        scores.append(trend_map.get(t.medium_term_trend, 0))

        if t.golden_cross:
            scores.append(0.6)
            reasons.append("Golden cross detected")
        elif t.death_cross:
            scores.append(-0.6)
            reasons.append("Death cross detected")

        if t.above_200_sma:
            scores.append(0.3)
            reasons.append("Above 200 SMA")
        elif data.moving_averages.sma_200 is not None:
            scores.append(-0.3)
            reasons.append("Below 200 SMA")

        if not scores:
            return SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.2,
                rationale="Insufficient technical data",
            )

        avg = sum(scores) / len(scores)
        confidence = min(0.85, len(scores) / 7.0 * 0.85)

        return SignalWithConfidence(
            signal=Signal.from_score(avg),
            confidence=round(confidence, 2),
            rationale="; ".join(reasons) if reasons else "Mixed signals",
        )


def _last_val(series: pd.Series) -> float | None:
    if series.empty:
        return None
    val = series.iloc[-1]
    if pd.isna(val) or np.isinf(val):
        return None
    return float(val)
