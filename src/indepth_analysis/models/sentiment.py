from pydantic import BaseModel


class AnalystRating(BaseModel):
    firm: str = ""
    rating: str = ""
    price_target: float | None = None


class SentimentData(BaseModel):
    analyst_count: int = 0
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    mean_target: float | None = None
    median_target: float | None = None
    high_target: float | None = None
    low_target: float | None = None
    current_price: float | None = None
    upside_pct: float | None = None
    recommendation: str = "N/A"
    recent_ratings: list[AnalystRating] = []
