from pydantic import BaseModel


class MovingAverages(BaseModel):
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    price_vs_sma20: float | None = None
    price_vs_sma50: float | None = None
    price_vs_sma200: float | None = None


class MomentumIndicators(BaseModel):
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    stochastic_k: float | None = None
    stochastic_d: float | None = None
    adx: float | None = None


class SupportResistance(BaseModel):
    support_levels: list[float] = []
    resistance_levels: list[float] = []
    nearest_support: float | None = None
    nearest_resistance: float | None = None
    distance_to_support_pct: float | None = None
    distance_to_resistance_pct: float | None = None


class TrendAnalysis(BaseModel):
    short_term_trend: str = "neutral"
    medium_term_trend: str = "neutral"
    long_term_trend: str = "neutral"
    golden_cross: bool = False
    death_cross: bool = False
    above_200_sma: bool = False


class TechnicalData(BaseModel):
    current_price: float | None = None
    moving_averages: MovingAverages = MovingAverages()
    momentum: MomentumIndicators = MomentumIndicators()
    support_resistance: SupportResistance = SupportResistance()
    trend: TrendAnalysis = TrendAnalysis()
