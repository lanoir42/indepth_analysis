from pydantic import BaseModel

from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.fundamental import FundamentalData
from indepth_analysis.models.macro import MacroData
from indepth_analysis.models.options import OptionsFlowSummary
from indepth_analysis.models.portfolio import PortfolioContext
from indepth_analysis.models.sentiment import SentimentData
from indepth_analysis.models.technical import TechnicalData


class DimensionResult(BaseModel):
    name: str
    weight: float
    signal: SignalWithConfidence
    available: bool = True


class InvestmentReport(BaseModel):
    ticker: str
    company_name: str = ""
    current_price: float | None = None

    fundamental: FundamentalData | None = None
    technical: TechnicalData | None = None
    options: OptionsFlowSummary | None = None
    macro: MacroData | None = None
    sentiment: SentimentData | None = None
    portfolio: PortfolioContext | None = None

    fundamental_signal: SignalWithConfidence | None = None
    technical_signal: SignalWithConfidence | None = None
    options_signal: SignalWithConfidence | None = None
    macro_signal: SignalWithConfidence | None = None
    sentiment_signal: SignalWithConfidence | None = None
    portfolio_signal: SignalWithConfidence | None = None

    dimension_results: list[DimensionResult] = []
    overall_signal: Signal = Signal.NEUTRAL
    overall_confidence: float = 0.0
    overall_score: float = 0.0
    summary: str = ""
