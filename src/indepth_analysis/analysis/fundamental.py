import logging

import pandas as pd

from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.fundamental import (
    BalanceSheetHealth,
    FundamentalData,
    GrowthMetrics,
    MarginMetrics,
    ValuationMetrics,
)

logger = logging.getLogger(__name__)


def _safe_get(d: dict, *keys: str) -> float | None:
    for k in keys:
        val = d.get(k)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def _pct(val: float | None) -> float | None:
    if val is None:
        return None
    return val * 100.0


class FundamentalAnalyzer:
    def analyze(
        self,
        info: dict,
        financials: pd.DataFrame,
        balance_sheet: pd.DataFrame,
        cashflow: pd.DataFrame,
    ) -> tuple[FundamentalData, SignalWithConfidence]:
        valuation = self._extract_valuation(info)
        growth = self._extract_growth(info)
        margins = self._extract_margins(info, financials, cashflow)
        bs = self._extract_balance_sheet(info, balance_sheet)

        data = FundamentalData(
            valuation=valuation,
            growth=growth,
            margins=margins,
            balance_sheet=bs,
        )
        signal = self._score(data)
        return data, signal

    def _extract_valuation(self, info: dict) -> ValuationMetrics:
        return ValuationMetrics(
            pe_ratio=_safe_get(info, "trailingPE"),
            forward_pe=_safe_get(info, "forwardPE"),
            pb_ratio=_safe_get(info, "priceToBook"),
            ps_ratio=_safe_get(info, "priceToSalesTrailing12Months"),
            peg_ratio=_safe_get(info, "pegRatio"),
            ev_to_ebitda=_safe_get(info, "enterpriseToEbitda"),
            market_cap=_safe_get(info, "marketCap"),
        )

    def _extract_growth(self, info: dict) -> GrowthMetrics:
        return GrowthMetrics(
            revenue_growth_yoy=_pct(_safe_get(info, "revenueGrowth")),
            earnings_growth_yoy=_pct(_safe_get(info, "earningsGrowth")),
            revenue_growth_quarterly=_pct(_safe_get(info, "revenueQuarterlyGrowth")),
            earnings_growth_quarterly=_pct(_safe_get(info, "earningsQuarterlyGrowth")),
        )

    def _extract_margins(
        self,
        info: dict,
        financials: pd.DataFrame,
        cashflow: pd.DataFrame,
    ) -> MarginMetrics:
        gross = _pct(_safe_get(info, "grossMargins"))
        operating = _pct(_safe_get(info, "operatingMargins"))
        profit = _pct(_safe_get(info, "profitMargins"))

        fcf_margin = None
        if not financials.empty and not cashflow.empty:
            try:
                revenue = _get_latest(financials, "Total Revenue")
                fcf = _get_latest(cashflow, "Free Cash Flow")
                if revenue and fcf and revenue > 0:
                    fcf_margin = (fcf / revenue) * 100.0
            except Exception:
                pass

        return MarginMetrics(
            gross_margin=gross,
            operating_margin=operating,
            profit_margin=profit,
            fcf_margin=fcf_margin,
        )

    def _extract_balance_sheet(
        self,
        info: dict,
        balance_sheet: pd.DataFrame,
    ) -> BalanceSheetHealth:
        current_ratio = _safe_get(info, "currentRatio")
        de = _safe_get(info, "debtToEquity")
        if de is not None:
            de = de / 100.0

        return BalanceSheetHealth(
            current_ratio=current_ratio,
            debt_to_equity=de,
            interest_coverage=_safe_get(info, "interestCoverage"),
            cash_per_share=_safe_get(info, "totalCashPerShare"),
            total_cash=_safe_get(info, "totalCash"),
            total_debt=_safe_get(info, "totalDebt"),
        )

    def _score(self, data: FundamentalData) -> SignalWithConfidence:
        scores: list[float] = []
        reasons: list[str] = []

        v = data.valuation
        if v.pe_ratio is not None:
            if v.pe_ratio < 15:
                scores.append(0.8)
                reasons.append("Low P/E")
            elif v.pe_ratio < 25:
                scores.append(0.3)
                reasons.append("Moderate P/E")
            elif v.pe_ratio < 40:
                scores.append(-0.2)
                reasons.append("High P/E")
            else:
                scores.append(-0.6)
                reasons.append("Very high P/E")

        if v.peg_ratio is not None:
            if v.peg_ratio < 1.0:
                scores.append(0.7)
                reasons.append("PEG < 1 (undervalued)")
            elif v.peg_ratio < 2.0:
                scores.append(0.2)
                reasons.append("PEG reasonable")
            else:
                scores.append(-0.4)
                reasons.append("PEG elevated")

        g = data.growth
        if g.revenue_growth_yoy is not None:
            if g.revenue_growth_yoy > 20:
                scores.append(0.7)
                reasons.append("Strong revenue growth")
            elif g.revenue_growth_yoy > 5:
                scores.append(0.3)
                reasons.append("Moderate revenue growth")
            elif g.revenue_growth_yoy > 0:
                scores.append(0.0)
                reasons.append("Slow revenue growth")
            else:
                scores.append(-0.5)
                reasons.append("Revenue declining")

        m = data.margins
        if m.profit_margin is not None:
            if m.profit_margin > 20:
                scores.append(0.6)
                reasons.append("Strong profitability")
            elif m.profit_margin > 10:
                scores.append(0.3)
                reasons.append("Good profitability")
            elif m.profit_margin > 0:
                scores.append(0.0)
                reasons.append("Thin margins")
            else:
                scores.append(-0.5)
                reasons.append("Unprofitable")

        bs = data.balance_sheet
        if bs.debt_to_equity is not None:
            if bs.debt_to_equity < 0.5:
                scores.append(0.5)
                reasons.append("Low leverage")
            elif bs.debt_to_equity < 1.0:
                scores.append(0.2)
                reasons.append("Moderate leverage")
            elif bs.debt_to_equity < 2.0:
                scores.append(-0.2)
                reasons.append("High leverage")
            else:
                scores.append(-0.5)
                reasons.append("Very high leverage")

        if not scores:
            return SignalWithConfidence(
                signal=Signal.NEUTRAL,
                confidence=0.2,
                rationale="Insufficient fundamental data",
            )

        avg_score = sum(scores) / len(scores)
        confidence = min(0.9, len(scores) / 5.0 * 0.9)

        return SignalWithConfidence(
            signal=Signal.from_score(avg_score),
            confidence=round(confidence, 2),
            rationale="; ".join(reasons),
        )


def _get_latest(df: pd.DataFrame, row_label: str) -> float | None:
    if row_label in df.index and not df.empty:
        val = df.loc[row_label].dropna()
        if not val.empty:
            return float(val.iloc[0])
    return None
