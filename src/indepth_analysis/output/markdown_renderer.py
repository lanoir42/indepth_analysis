from __future__ import annotations

from datetime import date
from pathlib import Path

from indepth_analysis.models.news import CalendarEvent, NewsArticle
from indepth_analysis.models.report import InvestmentReport
from indepth_analysis.models.report_data import ReportData
from indepth_analysis.output.formatters import (
    confidence_bar,
    fmt_large_number,
    fmt_number,
    fmt_pct,
    fmt_price,
    fmt_ratio,
)


class MarkdownRenderer:
    def render(
        self,
        report: InvestmentReport,
        report_data: ReportData | None = None,
        chart_paths: dict[str, Path] | None = None,
        charts_rel_dir: str = "charts",
    ) -> str:
        sections: list[str] = []
        sections.append(self._render_header(report))

        # Technical table + charts
        if report.technical:
            sections.append(self._render_technical(report))
        self._append_chart_embeds(
            sections,
            chart_paths,
            charts_rel_dir,
            report.ticker,
            ["price", "rsi", "macd"],
        )

        # Fundamental table + chart
        if report.fundamental:
            sections.append(self._render_fundamental(report))
        self._append_chart_embeds(
            sections,
            chart_paths,
            charts_rel_dir,
            report.ticker,
            ["fundamentals"],
        )

        if report.options:
            sections.append(self._render_options(report))
        if report.macro:
            sections.append(self._render_macro(report))
        if report.sentiment:
            sections.append(self._render_sentiment(report))

        # Calendar events
        if report_data and report_data.calendar_events:
            sections.append(self._render_calendar(report_data.calendar_events))

        # News
        if report_data and report_data.news:
            sections.append(self._render_news(report_data.news))

        if report.portfolio:
            sections.append(self._render_portfolio(report))

        sections.append(self._render_signal_summary(report))
        sections.append(self._render_verdict(report))
        return "\n".join(sections)

    def _append_chart_embeds(
        self,
        sections: list[str],
        chart_paths: dict[str, Path] | None,
        charts_rel_dir: str,
        ticker: str,
        chart_names: list[str],
    ) -> None:
        if not chart_paths:
            return
        chart_labels = {
            "price": "Price & Moving Averages",
            "rsi": "RSI(14)",
            "macd": "MACD",
            "fundamentals": "Quarterly Fundamentals",
        }
        lines: list[str] = []
        for name in chart_names:
            if name in chart_paths:
                label = chart_labels.get(name, name)
                filename = chart_paths[name].name
                lines.append(f"![{label}]({charts_rel_dir}/{filename})")
        if lines:
            sections.append("\n".join(lines) + "\n")

    def _render_header(self, report: InvestmentReport) -> str:
        name = report.company_name or report.ticker
        price = fmt_price(report.current_price)
        today = date.today().isoformat()
        return (
            f"# Investment Analysis: {name} ({report.ticker})\n\n"
            f"**Price:** {price}  \n"
            f"**Date:** {today}\n"
        )

    def _render_fundamental(self, report: InvestmentReport) -> str:
        f = report.fundamental
        if not f:
            return ""
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

        lines = ["## Fundamental Analysis\n"]
        lines.append("| Metric | Value | Metric | Value |")
        lines.append("|--------|------:|--------|------:|")
        for r in rows:
            lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")

        if report.fundamental_signal:
            sig = report.fundamental_signal
            lines.append(
                f"| Signal | {sig.signal.value} |"
                f" Confidence | {confidence_bar(sig.confidence)} |"
            )

        return "\n".join(lines) + "\n"

    def _render_technical(self, report: InvestmentReport) -> str:
        t = report.technical
        if not t:
            return ""
        ma = t.moving_averages
        mom = t.momentum
        sr = t.support_resistance
        rows = [
            ("Price", fmt_price(t.current_price), "RSI(14)", fmt_number(mom.rsi_14)),
            (
                "SMA(20)",
                fmt_price(ma.sma_20),
                "vs SMA(20)",
                fmt_pct(ma.price_vs_sma20),
            ),
            (
                "SMA(50)",
                fmt_price(ma.sma_50),
                "vs SMA(50)",
                fmt_pct(ma.price_vs_sma50),
            ),
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

        lines = ["## Technical Analysis\n"]
        lines.append("| Metric | Value | Metric | Value |")
        lines.append("|--------|------:|--------|------:|")
        for r in rows:
            lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")

        if report.technical_signal:
            sig = report.technical_signal
            lines.append(
                f"| Signal | {sig.signal.value} |"
                f" Confidence | {confidence_bar(sig.confidence)} |"
            )

        return "\n".join(lines) + "\n"

    def _render_options(self, report: InvestmentReport) -> str:
        o = report.options
        if not o:
            return ""
        lines = ["## Options Flow\n"]
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        lines.append(f"| IV Current | {fmt_pct(o.iv_current)} |")
        lines.append(f"| IV Percentile | {fmt_pct(o.iv_percentile)} |")
        lines.append(f"| Put/Call Vol Ratio | {fmt_number(o.put_call_ratio)} |")
        lines.append(f"| Put/Call OI Ratio | {fmt_number(o.put_call_oi_ratio)} |")
        lines.append(f"| Total Call Volume | {fmt_number(o.total_call_volume, 0)} |")
        lines.append(f"| Total Put Volume | {fmt_number(o.total_put_volume, 0)} |")
        lines.append(f"| Max Pain | {fmt_price(o.max_pain)} |")

        if o.unusual_activity:
            for note in o.unusual_activity[:5]:
                lines.append(f"| Unusual | {note} |")

        if report.options_signal:
            sig = report.options_signal
            lines.append(f"| Signal | {sig.signal.value} |")

        return "\n".join(lines) + "\n"

    def _render_macro(self, report: InvestmentReport) -> str:
        m = report.macro
        if not m:
            return ""
        lines = ["## Macro & Sector\n"]
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        lines.append(f"| Sector | {m.sector.sector_name} |")
        lines.append(f"| Sector ETF | {m.sector.sector_etf} |")
        lines.append(f"| Sector 1M | {fmt_pct(m.sector.sector_return_1m)} |")
        lines.append(f"| vs Sector 1M | {fmt_pct(m.sector.stock_vs_sector_1m)} |")
        lines.append(f"| vs Sector 3M | {fmt_pct(m.sector.stock_vs_sector_3m)} |")
        lines.append(f"| SPY 1M | {fmt_pct(m.spy_return_1m)} |")
        lines.append(f"| vs SPY 1M | {fmt_pct(m.stock_vs_market_1m)} |")
        lines.append(f"| 10Y Yield | {fmt_pct(m.rates.ten_year_yield)} |")
        lines.append(f"| Rate Trend | {m.rates.rate_trend} |")

        if report.macro_signal:
            sig = report.macro_signal
            lines.append(f"| Signal | {sig.signal.value} |")

        return "\n".join(lines) + "\n"

    def _render_sentiment(self, report: InvestmentReport) -> str:
        s = report.sentiment
        if not s:
            return ""
        low = fmt_price(s.low_target)
        high = fmt_price(s.high_target)
        lines = ["## Analyst Sentiment\n"]
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        lines.append(f"| Consensus | {s.recommendation} |")
        lines.append(f"| Analysts | {s.analyst_count} |")
        lines.append(
            f"| Buy / Hold / Sell | {s.buy_count} / {s.hold_count} / {s.sell_count} |"
        )
        lines.append(f"| Mean Target | {fmt_price(s.mean_target)} |")
        lines.append(f"| Median Target | {fmt_price(s.median_target)} |")
        lines.append(f"| Range | {low} — {high} |")
        lines.append(f"| Upside | {fmt_pct(s.upside_pct)} |")

        if report.sentiment_signal:
            sig = report.sentiment_signal
            lines.append(f"| Signal | {sig.signal.value} |")

        return "\n".join(lines) + "\n"

    def _render_calendar(self, events: list[CalendarEvent]) -> str:
        lines = ["## Upcoming Events\n"]
        lines.append("| Date | Event | Details |")
        lines.append("|------|-------|---------|")
        for ev in events:
            lines.append(f"| {ev.date} | {ev.event} | {ev.details} |")
        return "\n".join(lines) + "\n"

    def _render_news(self, articles: list[NewsArticle]) -> str:
        lines = ["## Recent News\n"]
        for article in articles:
            lines.append(f"### [{article.title}]({article.link})\n")
            if article.thumbnail:
                lines.append(f"![thumbnail]({article.thumbnail.url})\n")
            meta_parts = []
            if article.publisher:
                meta_parts.append(f"**{article.publisher}**")
            if article.published:
                meta_parts.append(article.published)
            if meta_parts:
                lines.append(" | ".join(meta_parts) + "\n")
        return "\n".join(lines)

    def _render_portfolio(self, report: InvestmentReport) -> str:
        p = report.portfolio
        if not p:
            return ""
        lines = ["## Portfolio Context\n"]
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        lines.append(f"| Portfolio Value | {fmt_large_number(p.total_value)} |")
        lines.append(f"| Current Weight | {fmt_pct(p.current_weight)} |")
        lines.append(f"| Sector Conc. | {fmt_pct(p.sector_concentration)} |")
        lines.append(f"| Max Correlation | {fmt_number(p.max_correlation)} |")
        lines.append(f"| Diversif. Score | {fmt_number(p.diversification_score)} |")

        if p.top_correlations:
            top = sorted(p.top_correlations.items(), key=lambda x: -abs(x[1]))[:5]
            for ticker, corr in top:
                lines.append(f"| Corr w/ {ticker} | {fmt_number(corr)} |")

        if report.portfolio_signal:
            sig = report.portfolio_signal
            lines.append(f"| Signal | {sig.signal.value} |")

        return "\n".join(lines) + "\n"

    def _render_signal_summary(self, report: InvestmentReport) -> str:
        if not report.dimension_results:
            return ""
        lines = ["## Signal Summary\n"]
        lines.append("| Dimension | Weight | Signal | Confidence | Score |")
        lines.append("|-----------|-------:|:------:|:----------:|------:|")

        for dim in report.dimension_results:
            if not dim.available:
                lines.append(
                    f"| {dim.name} | {fmt_pct(dim.weight * 100, 0)} | — | — | — |"
                )
                continue
            sig = dim.signal
            lines.append(
                f"| {dim.name} | {dim.weight * 100:.0f}% |"
                f" {sig.signal.value} |"
                f" {confidence_bar(sig.confidence)} |"
                f" {fmt_number(sig.weighted_score)} |"
            )

        return "\n".join(lines) + "\n"

    def _render_verdict(self, report: InvestmentReport) -> str:
        score = f"{report.overall_score:+.2f}"
        conf = f"{report.overall_confidence:.0%}"
        lines = ["## Overall Assessment\n"]
        lines.append(f"**Verdict:** {report.overall_signal.value}  ")
        lines.append(f"**Score:** {score} | **Confidence:** {conf}\n")
        if report.summary:
            lines.append(f"> {report.summary}\n")
        return "\n".join(lines)
