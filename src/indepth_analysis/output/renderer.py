from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from indepth_analysis.models.report import InvestmentReport
from indepth_analysis.output.formatters import (
    confidence_bar,
    fmt_large_number,
    fmt_number,
    fmt_pct,
    fmt_price,
    fmt_ratio,
    signal_color,
)


class ReportRenderer:
    def __init__(self) -> None:
        self.console = Console()

    def render(self, report: InvestmentReport) -> None:
        self._render_header(report)
        if report.fundamental:
            self._render_fundamental(report)
        if report.technical:
            self._render_technical(report)
        if report.options:
            self._render_options(report)
        if report.macro:
            self._render_macro(report)
        if report.sentiment:
            self._render_sentiment(report)
        if report.portfolio:
            self._render_portfolio(report)
        self._render_signal_summary(report)
        self._render_verdict(report)

    def _render_header(self, report: InvestmentReport) -> None:
        name = report.company_name or report.ticker
        price = fmt_price(report.current_price)
        self.console.print()
        self.console.print(
            Panel(
                f"[bold]{name}[/bold] ({report.ticker})  —  {price}",
                title="Investment Analysis",
                style="cyan",
            )
        )

    def _render_fundamental(self, report: InvestmentReport) -> None:
        f = report.fundamental
        if not f:
            return
        table = Table(title="Fundamental Analysis", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        v = f.valuation
        g = f.growth
        m = f.margins
        b = f.balance_sheet
        rows = [
            ("P/E", fmt_number(v.pe_ratio), "Fwd P/E", fmt_number(v.forward_pe)),
            ("P/B", fmt_number(v.pb_ratio), "P/S", fmt_number(v.ps_ratio)),
            ("PEG", fmt_number(v.peg_ratio), "EV/EBITDA", fmt_number(v.ev_to_ebitda)),
            (
                "Rev Growth",
                fmt_pct(g.revenue_growth_yoy),
                "EPS Growth",
                fmt_pct(g.earnings_growth_yoy),
            ),
            (
                "Gross Margin",
                fmt_pct(m.gross_margin),
                "Op Margin",
                fmt_pct(m.operating_margin),
            ),
            (
                "Profit Margin",
                fmt_pct(m.profit_margin),
                "FCF Margin",
                fmt_pct(m.fcf_margin),
            ),
            (
                "Current Ratio",
                fmt_ratio(b.current_ratio),
                "D/E",
                fmt_ratio(b.debt_to_equity),
            ),
            (
                "Mkt Cap",
                fmt_large_number(v.market_cap),
                "Cash",
                fmt_large_number(b.total_cash),
            ),
        ]
        for r in rows:
            table.add_row(*r)

        if report.fundamental_signal:
            sig = report.fundamental_signal
            table.add_row(
                "Signal",
                Text(sig.signal.value, style=signal_color(sig.signal)),
                "Confidence",
                confidence_bar(sig.confidence),
            )

        self.console.print(table)

    def _render_technical(self, report: InvestmentReport) -> None:
        t = report.technical
        if not t:
            return
        table = Table(title="Technical Analysis", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        ma = t.moving_averages
        mom = t.momentum
        sr = t.support_resistance
        rows = [
            ("Price", fmt_price(t.current_price), "RSI(14)", fmt_number(mom.rsi_14)),
            ("SMA(20)", fmt_price(ma.sma_20), "vs SMA(20)", fmt_pct(ma.price_vs_sma20)),
            ("SMA(50)", fmt_price(ma.sma_50), "vs SMA(50)", fmt_pct(ma.price_vs_sma50)),
            (
                "SMA(200)",
                fmt_price(ma.sma_200),
                "vs SMA(200)",
                fmt_pct(ma.price_vs_sma200),
            ),
            ("MACD", fmt_number(mom.macd), "MACD Sig", fmt_number(mom.macd_signal)),
            (
                "Support",
                fmt_price(sr.nearest_support),
                "Resistance",
                fmt_price(sr.nearest_resistance),
            ),
            (
                "Short Trend",
                t.trend.short_term_trend,
                "Med Trend",
                t.trend.medium_term_trend,
            ),
        ]
        for r in rows:
            table.add_row(*r)

        if report.technical_signal:
            sig = report.technical_signal
            table.add_row(
                "Signal",
                Text(sig.signal.value, style=signal_color(sig.signal)),
                "Confidence",
                confidence_bar(sig.confidence),
            )

        self.console.print(table)

    def _render_options(self, report: InvestmentReport) -> None:
        o = report.options
        if not o:
            return
        table = Table(title="Options Flow", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("IV Current", fmt_pct(o.iv_current))
        table.add_row("IV Percentile", fmt_pct(o.iv_percentile))
        table.add_row("Put/Call Vol Ratio", fmt_number(o.put_call_ratio))
        table.add_row("Put/Call OI Ratio", fmt_number(o.put_call_oi_ratio))
        table.add_row("Total Call Volume", fmt_number(o.total_call_volume, 0))
        table.add_row("Total Put Volume", fmt_number(o.total_put_volume, 0))
        table.add_row("Max Pain", fmt_price(o.max_pain))

        if o.unusual_activity:
            for note in o.unusual_activity[:5]:
                table.add_row("Unusual", note)

        if report.options_signal:
            sig = report.options_signal
            table.add_row(
                "Signal",
                Text(sig.signal.value, style=signal_color(sig.signal)),
            )

        self.console.print(table)

    def _render_macro(self, report: InvestmentReport) -> None:
        m = report.macro
        if not m:
            return
        table = Table(title="Macro & Sector", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Sector", m.sector.sector_name)
        table.add_row("Sector ETF", m.sector.sector_etf)
        table.add_row("Sector 1M", fmt_pct(m.sector.sector_return_1m))
        table.add_row("vs Sector 1M", fmt_pct(m.sector.stock_vs_sector_1m))
        table.add_row("vs Sector 3M", fmt_pct(m.sector.stock_vs_sector_3m))
        table.add_row("SPY 1M", fmt_pct(m.spy_return_1m))
        table.add_row("vs SPY 1M", fmt_pct(m.stock_vs_market_1m))
        table.add_row("10Y Yield", fmt_pct(m.rates.ten_year_yield))
        table.add_row("Rate Trend", m.rates.rate_trend)

        if report.macro_signal:
            sig = report.macro_signal
            table.add_row(
                "Signal",
                Text(sig.signal.value, style=signal_color(sig.signal)),
            )

        self.console.print(table)

    def _render_sentiment(self, report: InvestmentReport) -> None:
        s = report.sentiment
        if not s:
            return
        table = Table(title="Analyst Sentiment", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Consensus", s.recommendation)
        table.add_row("Analysts", str(s.analyst_count))
        table.add_row(
            "Buy / Hold / Sell",
            f"{s.buy_count} / {s.hold_count} / {s.sell_count}",
        )
        table.add_row("Mean Target", fmt_price(s.mean_target))
        table.add_row("Median Target", fmt_price(s.median_target))
        low = fmt_price(s.low_target)
        high = fmt_price(s.high_target)
        table.add_row("Range", f"{low} — {high}")
        table.add_row("Upside", fmt_pct(s.upside_pct))

        if report.sentiment_signal:
            sig = report.sentiment_signal
            table.add_row(
                "Signal",
                Text(sig.signal.value, style=signal_color(sig.signal)),
            )

        self.console.print(table)

    def _render_portfolio(self, report: InvestmentReport) -> None:
        p = report.portfolio
        if not p:
            return
        table = Table(title="Portfolio Context", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Portfolio Value", fmt_large_number(p.total_value))
        table.add_row("Current Weight", fmt_pct(p.current_weight))
        table.add_row("Sector Conc.", fmt_pct(p.sector_concentration))
        table.add_row("Max Correlation", fmt_number(p.max_correlation))
        table.add_row("Diversif. Score", fmt_number(p.diversification_score))

        if p.top_correlations:
            top = sorted(p.top_correlations.items(), key=lambda x: -abs(x[1]))[:5]
            for ticker, corr in top:
                table.add_row(f"  Corr w/ {ticker}", fmt_number(corr))

        if report.portfolio_signal:
            sig = report.portfolio_signal
            table.add_row(
                "Signal",
                Text(sig.signal.value, style=signal_color(sig.signal)),
            )

        self.console.print(table)

    def _render_signal_summary(self, report: InvestmentReport) -> None:
        if not report.dimension_results:
            return
        table = Table(title="Signal Summary", show_header=True)
        table.add_column("Dimension", style="cyan")
        table.add_column("Weight", justify="right")
        table.add_column("Signal", justify="center")
        table.add_column("Confidence", justify="center")
        table.add_column("Score", justify="right")

        for dim in report.dimension_results:
            if not dim.available:
                table.add_row(
                    dim.name,
                    fmt_pct(dim.weight * 100, 0),
                    "—",
                    "—",
                    "—",
                    style="dim",
                )
                continue
            sig = dim.signal
            table.add_row(
                dim.name,
                f"{dim.weight * 100:.0f}%",
                Text(sig.signal.value, style=signal_color(sig.signal)),
                confidence_bar(sig.confidence),
                fmt_number(sig.weighted_score),
            )

        self.console.print(table)

    def _render_verdict(self, report: InvestmentReport) -> None:
        color = signal_color(report.overall_signal)
        verdict = Text()
        verdict.append("\n  Verdict: ", style="bold")
        verdict.append(report.overall_signal.value, style=color)
        score = f"{report.overall_score:+.2f}"
        conf = f"{report.overall_confidence:.0%}"
        verdict.append(f"  (score: {score}, confidence: {conf})")
        verdict.append(f"\n\n  {report.summary}\n", style="dim")
        self.console.print(Panel(verdict, title="Overall Assessment", style=color))
