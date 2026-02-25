from pydantic import BaseModel


class SectorPerformance(BaseModel):
    sector_name: str = ""
    sector_etf: str = ""
    sector_return_1m: float | None = None
    sector_return_3m: float | None = None
    sector_return_6m: float | None = None
    sector_return_1y: float | None = None
    stock_vs_sector_1m: float | None = None
    stock_vs_sector_3m: float | None = None
    stock_vs_sector_6m: float | None = None
    relative_strength: float | None = None


class RateEnvironment(BaseModel):
    ten_year_yield: float | None = None
    two_year_yield: float | None = None
    yield_curve_spread: float | None = None
    fed_funds_rate: float | None = None
    rate_trend: str = "unknown"


class MacroData(BaseModel):
    sector: SectorPerformance = SectorPerformance()
    rates: RateEnvironment = RateEnvironment()
    spy_return_1m: float | None = None
    spy_return_3m: float | None = None
    stock_vs_market_1m: float | None = None
    stock_vs_market_3m: float | None = None
