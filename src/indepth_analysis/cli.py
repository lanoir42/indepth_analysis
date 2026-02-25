import argparse
import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from rich.console import Console

from indepth_analysis.config import AnalysisConfig
from indepth_analysis.data.market_data import MarketDataProvider
from indepth_analysis.models.report import InvestmentReport
from indepth_analysis.models.report_data import ReportData
from indepth_analysis.output.renderer import ReportRenderer

logger = logging.getLogger(__name__)
console = Console()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="indepth",
        description="Full-spectrum investment analysis",
    )
    p.add_argument("ticker", help="Stock ticker symbol")
    p.add_argument(
        "--ibkr-host",
        default="127.0.0.1",
        help="IBKR TWS/Gateway host",
    )
    p.add_argument(
        "--ibkr-port",
        type=int,
        default=7497,
        help="IBKR TWS/Gateway port",
    )
    p.add_argument(
        "--sheets-id",
        default=None,
        help="Google Sheets ID for portfolio",
    )
    p.add_argument(
        "--credentials",
        default=None,
        help="Path to Google service account JSON",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return p


async def run_analysis(
    ticker: str, config: AnalysisConfig
) -> tuple[InvestmentReport, ReportData]:
    provider = MarketDataProvider(ticker, config)
    executor = ThreadPoolExecutor(max_workers=4)
    loop = asyncio.get_event_loop()

    with console.status(f"[cyan]Connecting to data sources for {ticker}..."):
        await provider.initialize()

    with console.status("[cyan]Fetching market data..."):
        (
            info,
            history,
            financials,
            balance_sheet,
            cashflow,
            recs,
            news_raw,
            calendar_raw,
            quarterly_financials,
        ) = await asyncio.gather(
            loop.run_in_executor(executor, provider.get_info),
            loop.run_in_executor(executor, provider.get_history),
            loop.run_in_executor(executor, provider.get_financials),
            loop.run_in_executor(executor, provider.get_balance_sheet),
            loop.run_in_executor(executor, provider.get_cashflow),
            loop.run_in_executor(executor, provider.get_recommendations),
            loop.run_in_executor(executor, provider.get_news),
            loop.run_in_executor(executor, provider.get_calendar),
            loop.run_in_executor(executor, provider.get_quarterly_financials),
        )

    company_name = info.get("longName", info.get("shortName", ticker))
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    report = InvestmentReport(
        ticker=ticker.upper(),
        company_name=company_name or ticker,
        current_price=current_price,
    )

    with console.status("[cyan]Running fundamental analysis..."):
        from indepth_analysis.analysis.fundamental import (
            FundamentalAnalyzer,
        )

        fa = FundamentalAnalyzer()
        fund_data, fund_signal = fa.analyze(info, financials, balance_sheet, cashflow)
        report.fundamental = fund_data
        report.fundamental_signal = fund_signal

    with console.status("[cyan]Running technical analysis..."):
        from indepth_analysis.analysis.technical import (
            TechnicalAnalyzer,
        )

        ta = TechnicalAnalyzer()
        tech_data, tech_signal, indicator_series = ta.analyze(history, current_price)
        report.technical = tech_data
        report.technical_signal = tech_signal

    with console.status("[cyan]Running macro & sector analysis..."):
        from indepth_analysis.analysis.macro import MacroAnalyzer

        sector = info.get("sector", "")
        ma = MacroAnalyzer()
        macro_data, macro_signal = await ma.analyze(
            ticker, sector, history, provider, loop, executor
        )
        report.macro = macro_data
        report.macro_signal = macro_signal

    with console.status("[cyan]Running sentiment analysis..."):
        from indepth_analysis.analysis.sentiment import (
            SentimentAnalyzer,
        )

        sa = SentimentAnalyzer()
        sent_data, sent_signal = sa.analyze(info, recs, current_price)
        report.sentiment = sent_data
        report.sentiment_signal = sent_signal

    if provider.ibkr_available:
        with console.status("[cyan]Running options flow analysis..."):
            chain = await provider.get_option_chain()
            if chain:
                from indepth_analysis.analysis.options_flow import (
                    OptionsFlowAnalyzer,
                )

                oa = OptionsFlowAnalyzer()
                opts_data, opts_signal = oa.analyze(chain, current_price)
                report.options = opts_data
                report.options_signal = opts_signal

    if config.sheets_id and config.credentials_path:
        with console.status("[cyan]Fetching portfolio context..."):
            try:
                from indepth_analysis.analysis.portfolio import (
                    PortfolioAnalyzer,
                )
                from indepth_analysis.data.sheets_client import (
                    SheetsClient,
                )

                sc = SheetsClient(config.credentials_path, config.sheets_id)
                holdings = await loop.run_in_executor(executor, sc.read_holdings)
                pa = PortfolioAnalyzer()
                port_data, port_signal = await pa.analyze(
                    ticker,
                    holdings,
                    provider,
                    loop,
                    executor,
                )
                report.portfolio = port_data
                report.portfolio_signal = port_signal
            except Exception:
                logger.warning("Portfolio analysis unavailable")

    with console.status("[cyan]Generating final assessment..."):
        from indepth_analysis.analysis.aggregator import (
            InvestmentAggregator,
        )

        agg = InvestmentAggregator(config.weights)
        agg.aggregate(report)

    # Build ReportData sidecar
    from indepth_analysis.analysis.fundamentals_history import (
        extract_fundamentals_history,
    )
    from indepth_analysis.analysis.news_calendar import parse_calendar, parse_news

    report_data = ReportData(
        history=history,
        indicators=indicator_series,
        fundamentals_history=extract_fundamentals_history(quarterly_financials),
        news=parse_news(news_raw),
        calendar_events=parse_calendar(calendar_raw),
    )

    await provider.disconnect()
    executor.shutdown(wait=False)
    return report, report_data


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    config = AnalysisConfig(
        ibkr_host=args.ibkr_host,
        ibkr_port=args.ibkr_port,
        sheets_id=args.sheets_id,
        credentials_path=args.credentials,
    )

    try:
        report, report_data = asyncio.run(run_analysis(args.ticker, config))
        renderer = ReportRenderer()
        renderer.render(report)

        # Generate charts
        from indepth_analysis.output.charts import generate_all_charts

        reports_dir = Path("reports")
        charts_dir = reports_dir / "charts"
        chart_paths = generate_all_charts(report_data, report.ticker, charts_dir)

        if chart_paths:
            console.print(
                f"\n[green]Generated {len(chart_paths)} chart(s)"
                f" in {charts_dir}[/green]"
            )

        # Generate markdown report
        from indepth_analysis.output.markdown_renderer import MarkdownRenderer

        md_renderer = MarkdownRenderer()
        md_content = md_renderer.render(
            report,
            report_data=report_data,
            chart_paths=chart_paths,
            charts_rel_dir="charts",
        )
        reports_dir.mkdir(exist_ok=True)
        filename = f"{report.ticker}_{date.today().isoformat()}.md"
        filepath = reports_dir / filename
        filepath.write_text(md_content)
        console.print(f"[green]Report saved to {filepath}[/green]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
