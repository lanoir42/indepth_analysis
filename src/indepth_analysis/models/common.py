from enum import StrEnum

from pydantic import BaseModel, Field


class Signal(StrEnum):
    STRONG_BUY = "STRONG BUY"
    BUY = "BUY"
    LEAN_BUY = "LEAN BUY"
    NEUTRAL = "NEUTRAL"
    LEAN_SELL = "LEAN SELL"
    SELL = "SELL"
    STRONG_SELL = "STRONG SELL"

    @property
    def numeric(self) -> float:
        mapping = {
            Signal.STRONG_BUY: 1.0,
            Signal.BUY: 0.67,
            Signal.LEAN_BUY: 0.33,
            Signal.NEUTRAL: 0.0,
            Signal.LEAN_SELL: -0.33,
            Signal.SELL: -0.67,
            Signal.STRONG_SELL: -1.0,
        }
        return mapping[self]

    @staticmethod
    def from_score(score: float) -> "Signal":
        if score >= 0.8:
            return Signal.STRONG_BUY
        if score >= 0.5:
            return Signal.BUY
        if score >= 0.2:
            return Signal.LEAN_BUY
        if score >= -0.2:
            return Signal.NEUTRAL
        if score >= -0.5:
            return Signal.LEAN_SELL
        if score >= -0.8:
            return Signal.SELL
        return Signal.STRONG_SELL


class SignalWithConfidence(BaseModel):
    signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""

    @property
    def weighted_score(self) -> float:
        return self.signal.numeric * self.confidence


class AnalysisRequest(BaseModel):
    ticker: str
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    sheets_id: str | None = None
    credentials_path: str | None = None
