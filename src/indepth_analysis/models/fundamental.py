from pydantic import BaseModel


class ValuationMetrics(BaseModel):
    pe_ratio: float | None = None
    forward_pe: float | None = None
    pb_ratio: float | None = None
    ps_ratio: float | None = None
    peg_ratio: float | None = None
    ev_to_ebitda: float | None = None
    market_cap: float | None = None


class GrowthMetrics(BaseModel):
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    revenue_growth_quarterly: float | None = None
    earnings_growth_quarterly: float | None = None


class MarginMetrics(BaseModel):
    gross_margin: float | None = None
    operating_margin: float | None = None
    profit_margin: float | None = None
    fcf_margin: float | None = None


class BalanceSheetHealth(BaseModel):
    current_ratio: float | None = None
    debt_to_equity: float | None = None
    interest_coverage: float | None = None
    cash_per_share: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None


class FundamentalData(BaseModel):
    valuation: ValuationMetrics = ValuationMetrics()
    growth: GrowthMetrics = GrowthMetrics()
    margins: MarginMetrics = MarginMetrics()
    balance_sheet: BalanceSheetHealth = BalanceSheetHealth()
