from pydantic import BaseModel


class PortfolioHolding(BaseModel):
    ticker: str
    shares: float
    market_value: float | None = None
    weight: float | None = None
    cost_basis: float | None = None


class CorrelationMatrix(BaseModel):
    tickers: list[str] = []
    matrix: list[list[float]] = []
    target_correlations: dict[str, float] = {}


class PortfolioContext(BaseModel):
    holdings: list[PortfolioHolding] = []
    total_value: float | None = None
    target_weight: float | None = None
    current_weight: float | None = None
    sector_concentration: float | None = None
    top_correlations: dict[str, float] = {}
    max_correlation: float | None = None
    diversification_score: float | None = None
