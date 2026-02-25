from __future__ import annotations

import logging

import pandas as pd

from indepth_analysis.models.report_data import FundamentalsHistory

logger = logging.getLogger(__name__)


def extract_fundamentals_history(
    quarterly_financials: pd.DataFrame,
) -> FundamentalsHistory:
    if quarterly_financials is None or quarterly_financials.empty:
        return FundamentalsHistory()

    try:
        # yfinance quarterly_financials: rows are line items, columns are dates
        # Columns are sorted newest-first; reverse for chronological order
        cols = list(quarterly_financials.columns)
        cols.reverse()

        dates = [
            c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c) for c in cols
        ]

        def _row_values(labels: list[str]) -> list[float]:
            for label in labels:
                if label in quarterly_financials.index:
                    return [
                        float(quarterly_financials.loc[label, c])
                        if pd.notna(quarterly_financials.loc[label, c])
                        else 0.0
                        for c in cols
                    ]
            return []

        revenue = _row_values(["Total Revenue", "Revenue"])
        net_income = _row_values(["Net Income", "Net Income Common Stockholders"])
        gross_profit = _row_values(["Gross Profit"])

        # Compute margins as percentages
        gross_margin: list[float] = []
        operating_margin: list[float] = []
        profit_margin: list[float] = []

        if revenue:
            operating_income = _row_values(
                ["Operating Income", "EBIT", "Operating Revenue"]
            )
            for i, rev in enumerate(revenue):
                if rev and rev != 0:
                    gp = gross_profit[i] if i < len(gross_profit) else 0.0
                    gross_margin.append(gp / rev * 100)

                    oi = operating_income[i] if i < len(operating_income) else 0.0
                    operating_margin.append(oi / rev * 100)

                    ni = net_income[i] if i < len(net_income) else 0.0
                    profit_margin.append(ni / rev * 100)
                else:
                    gross_margin.append(0.0)
                    operating_margin.append(0.0)
                    profit_margin.append(0.0)

        return FundamentalsHistory(
            dates=dates,
            revenue=revenue,
            net_income=net_income,
            gross_margin=gross_margin,
            operating_margin=operating_margin,
            profit_margin=profit_margin,
        )
    except Exception:
        logger.warning("Failed to extract fundamentals history", exc_info=True)
        return FundamentalsHistory()
