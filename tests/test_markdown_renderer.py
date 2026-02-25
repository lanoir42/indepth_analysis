from pathlib import Path

from indepth_analysis.models.common import Signal, SignalWithConfidence
from indepth_analysis.models.fundamental import (
    BalanceSheetHealth,
    FundamentalData,
    GrowthMetrics,
    MarginMetrics,
    ValuationMetrics,
)
from indepth_analysis.models.macro import MacroData, RateEnvironment, SectorPerformance
from indepth_analysis.models.news import CalendarEvent, NewsArticle, NewsThumbnail
from indepth_analysis.models.options import OptionsFlowSummary
from indepth_analysis.models.portfolio import PortfolioContext
from indepth_analysis.models.report import DimensionResult, InvestmentReport
from indepth_analysis.models.report_data import ReportData
from indepth_analysis.models.sentiment import SentimentData
from indepth_analysis.models.technical import (
    MomentumIndicators,
    MovingAverages,
    SupportResistance,
    TechnicalData,
    TrendAnalysis,
)
from indepth_analysis.output.markdown_renderer import MarkdownRenderer


def _make_report() -> InvestmentReport:
    fund_signal = SignalWithConfidence(
        signal=Signal.BUY, confidence=0.8, rationale="solid"
    )
    tech_signal = SignalWithConfidence(
        signal=Signal.LEAN_BUY, confidence=0.6, rationale="trend up"
    )
    macro_signal = SignalWithConfidence(
        signal=Signal.NEUTRAL, confidence=0.5, rationale="mixed"
    )
    sent_signal = SignalWithConfidence(
        signal=Signal.BUY, confidence=0.7, rationale="analysts like it"
    )

    return InvestmentReport(
        ticker="MSFT",
        company_name="Microsoft Corporation",
        current_price=420.50,
        fundamental=FundamentalData(
            valuation=ValuationMetrics(
                pe_ratio=35.2, forward_pe=30.1, market_cap=3.1e12
            ),
            growth=GrowthMetrics(revenue_growth_yoy=12.5, earnings_growth_yoy=15.3),
            margins=MarginMetrics(gross_margin=69.4, operating_margin=44.6),
            balance_sheet=BalanceSheetHealth(
                current_ratio=1.77, debt_to_equity=0.42, total_cash=75.5e9
            ),
        ),
        fundamental_signal=fund_signal,
        technical=TechnicalData(
            current_price=420.50,
            moving_averages=MovingAverages(sma_20=415.0, sma_50=400.0, sma_200=380.0),
            momentum=MomentumIndicators(rsi_14=58.3, macd=2.5, macd_signal=1.8),
            support_resistance=SupportResistance(
                nearest_support=400.0, nearest_resistance=440.0
            ),
            trend=TrendAnalysis(
                short_term_trend="bullish", medium_term_trend="bullish"
            ),
        ),
        technical_signal=tech_signal,
        macro=MacroData(
            sector=SectorPerformance(
                sector_name="Technology",
                sector_etf="XLK",
                sector_return_1m=3.5,
                stock_vs_sector_1m=1.2,
                stock_vs_sector_3m=2.1,
            ),
            rates=RateEnvironment(ten_year_yield=4.25, rate_trend="rising"),
            spy_return_1m=2.1,
            stock_vs_market_1m=1.5,
        ),
        macro_signal=macro_signal,
        sentiment=SentimentData(
            analyst_count=30,
            buy_count=22,
            hold_count=6,
            sell_count=2,
            mean_target=460.0,
            median_target=455.0,
            high_target=520.0,
            low_target=350.0,
            upside_pct=9.4,
            recommendation="Buy",
        ),
        sentiment_signal=sent_signal,
        dimension_results=[
            DimensionResult(
                name="Fundamental", weight=0.30, signal=fund_signal, available=True
            ),
            DimensionResult(
                name="Technical", weight=0.20, signal=tech_signal, available=True
            ),
            DimensionResult(
                name="Options",
                weight=0.15,
                signal=SignalWithConfidence(signal=Signal.NEUTRAL, confidence=0.0),
                available=False,
            ),
            DimensionResult(
                name="Macro", weight=0.15, signal=macro_signal, available=True
            ),
            DimensionResult(
                name="Sentiment", weight=0.10, signal=sent_signal, available=True
            ),
        ],
        overall_signal=Signal.BUY,
        overall_confidence=0.65,
        overall_score=0.45,
        summary="MSFT shows solid fundamentals with strong growth.",
    )


class TestMarkdownRenderer:
    def setup_method(self):
        self.renderer = MarkdownRenderer()
        self.report = _make_report()
        self.md = self.renderer.render(self.report)

    def test_header_present(self):
        assert "# Investment Analysis: Microsoft Corporation (MSFT)" in self.md

    def test_price_in_header(self):
        assert "$420.50" in self.md

    def test_fundamental_section(self):
        assert "## Fundamental Analysis" in self.md
        assert "P/E" in self.md
        assert "35.20" in self.md

    def test_technical_section(self):
        assert "## Technical Analysis" in self.md
        assert "RSI(14)" in self.md
        assert "SMA(20)" in self.md

    def test_macro_section(self):
        assert "## Macro & Sector" in self.md
        assert "Technology" in self.md
        assert "XLK" in self.md

    def test_sentiment_section(self):
        assert "## Analyst Sentiment" in self.md
        assert "22 / 6 / 2" in self.md
        assert "$460.00" in self.md

    def test_signal_summary(self):
        assert "## Signal Summary" in self.md
        assert "Fundamental" in self.md
        assert "BUY" in self.md

    def test_verdict(self):
        assert "## Overall Assessment" in self.md
        assert "BUY" in self.md
        assert "+0.45" in self.md
        assert "65%" in self.md

    def test_summary_blockquote(self):
        assert "> MSFT shows solid fundamentals" in self.md

    def test_unavailable_dimension_shows_dash(self):
        assert "Options" in self.md
        assert "—" in self.md

    def test_no_options_section_when_none(self):
        assert "## Options Flow" not in self.md

    def test_no_portfolio_section_when_none(self):
        assert "## Portfolio Context" not in self.md

    def test_options_section_when_present(self):
        self.report.options = OptionsFlowSummary(
            iv_current=0.32,
            iv_percentile=0.65,
            put_call_ratio=0.85,
            max_pain=415.0,
        )
        self.report.options_signal = SignalWithConfidence(
            signal=Signal.LEAN_BUY, confidence=0.5
        )
        md = self.renderer.render(self.report)
        assert "## Options Flow" in md
        assert "$415.00" in md

    def test_portfolio_section_when_present(self):
        self.report.portfolio = PortfolioContext(
            total_value=500_000.0,
            current_weight=5.2,
            sector_concentration=25.0,
            max_correlation=0.82,
            diversification_score=7.5,
            top_correlations={"AAPL": 0.82, "GOOG": 0.75},
        )
        self.report.portfolio_signal = SignalWithConfidence(
            signal=Signal.NEUTRAL, confidence=0.6
        )
        md = self.renderer.render(self.report)
        assert "## Portfolio Context" in md
        assert "AAPL" in md

    def test_backward_compatibility(self):
        """render() works with just the report (no report_data or chart_paths)."""
        md = self.renderer.render(self.report)
        assert "## Technical Analysis" in md
        assert "## Fundamental Analysis" in md
        assert "## Overall Assessment" in md

    def test_chart_embeds(self):
        chart_paths = {
            "price": Path("reports/charts/MSFT_price.png"),
            "rsi": Path("reports/charts/MSFT_rsi.png"),
            "macd": Path("reports/charts/MSFT_macd.png"),
            "fundamentals": Path("reports/charts/MSFT_fundamentals.png"),
        }
        md = self.renderer.render(self.report, chart_paths=chart_paths)
        assert "![Price & Moving Averages](charts/MSFT_price.png)" in md
        assert "![RSI(14)](charts/MSFT_rsi.png)" in md
        assert "![MACD](charts/MSFT_macd.png)" in md
        assert "![Quarterly Fundamentals](charts/MSFT_fundamentals.png)" in md

    def test_calendar_section(self):
        report_data = ReportData(
            calendar_events=[
                CalendarEvent(
                    date="2025-01-28", event="Earnings", details="EPS Est: 2.95"
                ),
                CalendarEvent(date="2025-03-15", event="Dividend", details=""),
            ]
        )
        md = self.renderer.render(self.report, report_data=report_data)
        assert "## Upcoming Events" in md
        assert "2025-01-28" in md
        assert "Earnings" in md
        assert "Dividend" in md

    def test_news_section(self):
        report_data = ReportData(
            news=[
                NewsArticle(
                    title="MSFT Beats Earnings",
                    publisher="Reuters",
                    link="https://reuters.com/msft",
                    published="2025-01-28 21:00 UTC",
                    thumbnail=NewsThumbnail(
                        url="https://img.com/thumb.jpg", width=800, height=400
                    ),
                ),
            ]
        )
        md = self.renderer.render(self.report, report_data=report_data)
        assert "## Recent News" in md
        assert "[MSFT Beats Earnings](https://reuters.com/msft)" in md
        assert "![thumbnail](https://img.com/thumb.jpg)" in md
        assert "**Reuters**" in md

    def test_no_calendar_or_news_without_report_data(self):
        md = self.renderer.render(self.report)
        assert "## Upcoming Events" not in md
        assert "## Recent News" not in md
