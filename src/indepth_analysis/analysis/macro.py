import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from indepth_analysis.config import SECTOR_ETF_MAP
from indepth_analysis.data.market_data import MarketDataProvider
from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.macro import (
    MacroData,
    RateEnvironment,
    SectorPerformance,
)

logger = logging.getLogger(__name__)


def _period_return(df: pd.DataFrame, days: int) -> float | None:
    if df.empty or len(df) < days:
        return None
    close = df["Close"]
    start = float(close.iloc[-days])
    end = float(close.iloc[-1])
    if start == 0:
        return None
    return ((end / start) - 1) * 100


class MacroAnalyzer:
    async def analyze(
        self,
        ticker: str,
        sector: str,
        stock_history: pd.DataFrame,
        provider: MarketDataProvider,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
    ) -> tuple[MacroData, SignalWithConfidence]:
        etf = SECTOR_ETF_MAP.get(sector, "XLK")
        spy_hist, sector_hist, tny_hist = await asyncio.gather(
            loop.run_in_executor(executor, provider.get_sector_history, "SPY"),
            loop.run_in_executor(executor, provider.get_sector_history, etf),
            loop.run_in_executor(executor, provider.get_sector_history, "^TNX"),
        )

        stock_1m = _period_return(stock_history, 21)
        stock_3m = _period_return(stock_history, 63)
        stock_6m = _period_return(stock_history, 126)

        spy_1m = _period_return(spy_hist, 21)
        spy_3m = _period_return(spy_hist, 63)

        sec_1m = _period_return(sector_hist, 21)
        sec_3m = _period_return(sector_hist, 63)
        sec_6m = _period_return(sector_hist, 126)
        sec_1y = _period_return(sector_hist, 252)

        def diff(a: float | None, b: float | None) -> float | None:
            if a is not None and b is not None:
                return a - b
            return None

        rs = diff(stock_3m, sec_3m)

        sector_perf = SectorPerformance(
            sector_name=sector or "Unknown",
            sector_etf=etf,
            sector_return_1m=sec_1m,
            sector_return_3m=sec_3m,
            sector_return_6m=sec_6m,
            sector_return_1y=sec_1y,
            stock_vs_sector_1m=diff(stock_1m, sec_1m),
            stock_vs_sector_3m=diff(stock_3m, sec_3m),
            stock_vs_sector_6m=diff(stock_6m, sec_6m),
            relative_strength=rs,
        )

        rates = self._analyze_rates(tny_hist)

        data = MacroData(
            sector=sector_perf,
            rates=rates,
            spy_return_1m=spy_1m,
            spy_return_3m=spy_3m,
            stock_vs_market_1m=diff(stock_1m, spy_1m),
            stock_vs_market_3m=diff(stock_3m, spy_3m),
        )

        signal = self._score(data)
        return data, signal

    def _analyze_rates(self, tny_hist: pd.DataFrame) -> RateEnvironment:
        if tny_hist.empty:
            return RateEnvironment()

        close = tny_hist["Close"]
        current = float(close.iloc[-1])
        prev = float(close.iloc[-63]) if len(close) >= 63 else float(close.iloc[0])

        trend = "stable"
        if current - prev > 0.5:
            trend = "rising"
        elif prev - current > 0.5:
            trend = "falling"

        return RateEnvironment(
            ten_year_yield=current,
            rate_trend=trend,
        )

    def _score(self, data: MacroData) -> SignalWithConfidence:
        scores: list[float] = []
        reasons: list[str] = []

        rs = data.sector.relative_strength
        if rs is not None:
            if rs > 5:
                scores.append(0.5)
                reasons.append("Outperforming sector")
            elif rs > 0:
                scores.append(0.2)
                reasons.append("Slightly above sector")
            elif rs > -5:
                scores.append(-0.2)
                reasons.append("Slightly below sector")
            else:
                scores.append(-0.5)
                reasons.append("Underperforming sector")

        vs_mkt = data.stock_vs_market_3m
        if vs_mkt is not None:
            if vs_mkt > 5:
                scores.append(0.4)
                reasons.append("Beating market")
            elif vs_mkt < -5:
                scores.append(-0.4)
                reasons.append("Lagging market")
            else:
                scores.append(0.0)
                reasons.append("In-line with market")

        if data.rates.rate_trend == "rising":
            scores.append(-0.2)
            reasons.append("Rising rate environment")
        elif data.rates.rate_trend == "falling":
            scores.append(0.2)
            reasons.append("Falling rate environment")

        if not scores:
            return SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.3,
                rationale="Limited macro data",
            )

        avg = sum(scores) / len(scores)
        confidence = min(0.7, len(scores) / 3.0 * 0.7)
        return SignalWithConfidence(
            signal=Signal.from_score(avg),
            confidence=round(confidence, 2),
            rationale="; ".join(reasons),
        )
