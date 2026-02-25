import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from indepth_analysis.data.market_data import MarketDataProvider
from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.portfolio import (
    PortfolioContext,
    PortfolioHolding,
)

logger = logging.getLogger(__name__)


class PortfolioAnalyzer:
    async def analyze(
        self,
        target_ticker: str,
        holdings: list[PortfolioHolding],
        provider: MarketDataProvider,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
    ) -> tuple[PortfolioContext, SignalWithConfidence]:
        if not holdings:
            return PortfolioContext(), SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.2,
                rationale="No portfolio data",
            )

        total_value = sum(h.market_value for h in holdings if h.market_value)
        for h in holdings:
            if h.market_value and total_value > 0:
                h.weight = (h.market_value / total_value) * 100

        target_upper = target_ticker.upper()
        current_weight = None
        for h in holdings:
            if h.ticker == target_upper:
                current_weight = h.weight
                break

        tickers = list({h.ticker for h in holdings})
        if target_upper not in tickers:
            tickers.append(target_upper)

        correlations = await self._compute_correlations(
            target_upper, tickers, provider, loop, executor
        )

        top_corr = {
            k: v for k, v in sorted(correlations.items(), key=lambda x: -abs(x[1]))[:5]
        }
        max_corr = max(abs(v) for v in correlations.values()) if correlations else None

        n = len(tickers)
        div_score = None
        if correlations and n > 1:
            mean_corr = np.mean([abs(v) for v in correlations.values()])
            div_score = max(0, (1 - mean_corr) * 100)

        ctx = PortfolioContext(
            holdings=holdings,
            total_value=total_value if total_value else None,
            current_weight=current_weight,
            top_correlations=top_corr,
            max_correlation=max_corr,
            diversification_score=div_score,
        )

        signal = self._score(ctx)
        return ctx, signal

    async def _compute_correlations(
        self,
        target: str,
        tickers: list[str],
        provider: MarketDataProvider,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
    ) -> dict[str, float]:
        async def fetch(t: str) -> tuple[str, pd.DataFrame]:
            df = await loop.run_in_executor(
                executor,
                provider.get_sector_history,
                t,
                "6mo",
            )
            return t, df

        results = await asyncio.gather(
            *[fetch(t) for t in tickers],
            return_exceptions=True,
        )

        returns_map: dict[str, pd.Series] = {}
        for r in results:
            if isinstance(r, Exception):
                continue
            t, df = r
            if not df.empty and len(df) > 10:
                returns_map[t] = df["Close"].pct_change().dropna()

        if target not in returns_map:
            return {}

        target_returns = returns_map[target]
        correlations: dict[str, float] = {}
        for t, ret in returns_map.items():
            if t == target:
                continue
            aligned = pd.concat([target_returns, ret], axis=1, join="inner")
            if len(aligned) > 10:
                corr = float(aligned.corr().iloc[0, 1])
                if not np.isnan(corr):
                    correlations[t] = round(corr, 3)

        return correlations

    def _score(self, ctx: PortfolioContext) -> SignalWithConfidence:
        scores: list[float] = []
        reasons: list[str] = []

        if ctx.current_weight is not None:
            if ctx.current_weight > 15:
                scores.append(-0.5)
                reasons.append("Already heavily concentrated")
            elif ctx.current_weight > 8:
                scores.append(-0.2)
                reasons.append("Moderately concentrated")
            elif ctx.current_weight > 0:
                scores.append(0.1)
                reasons.append("Existing small position")
            else:
                scores.append(0.3)
                reasons.append("New position adds diversification")

        if ctx.max_correlation is not None:
            if ctx.max_correlation > 0.8:
                scores.append(-0.3)
                reasons.append("High correlation with existing holdings")
            elif ctx.max_correlation < 0.4:
                scores.append(0.3)
                reasons.append("Low correlation — good diversifier")

        if ctx.diversification_score is not None:
            if ctx.diversification_score > 70:
                scores.append(0.2)
                reasons.append("Well-diversified portfolio")
            elif ctx.diversification_score < 30:
                scores.append(-0.2)
                reasons.append("Portfolio needs diversification")

        if not scores:
            return SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.3,
                rationale="Limited portfolio context",
            )

        avg = sum(scores) / len(scores)
        confidence = min(0.6, len(scores) / 3.0 * 0.6)
        return SignalWithConfidence(
            signal=Signal.from_score(avg),
            confidence=round(confidence, 2),
            rationale="; ".join(reasons),
        )
