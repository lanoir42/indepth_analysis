from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from indepth_analysis.models.news import CalendarEvent, NewsArticle


@dataclass
class IndicatorSeries:
    dates: pd.DatetimeIndex | None = None
    close: pd.Series | None = None
    sma_20: pd.Series | None = None
    sma_50: pd.Series | None = None
    sma_200: pd.Series | None = None
    rsi_14: pd.Series | None = None
    macd_line: pd.Series | None = None
    macd_signal: pd.Series | None = None
    macd_histogram: pd.Series | None = None
    volume: pd.Series | None = None


@dataclass
class FundamentalsHistory:
    dates: list[str] = field(default_factory=list)
    revenue: list[float] = field(default_factory=list)
    net_income: list[float] = field(default_factory=list)
    gross_margin: list[float] = field(default_factory=list)
    operating_margin: list[float] = field(default_factory=list)
    profit_margin: list[float] = field(default_factory=list)


@dataclass
class ReportData:
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    indicators: IndicatorSeries = field(default_factory=IndicatorSeries)
    fundamentals_history: FundamentalsHistory = field(
        default_factory=FundamentalsHistory
    )
    news: list[NewsArticle] = field(default_factory=list)
    calendar_events: list[CalendarEvent] = field(default_factory=list)
