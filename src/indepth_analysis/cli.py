import argparse
import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table

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
    sub = p.add_subparsers(dest="command")

    # --- analyze (default) ---
    analyze = sub.add_parser("analyze", help="Run investment analysis")
    analyze.add_argument("ticker", help="Stock ticker symbol")
    analyze.add_argument(
        "--ibkr-host",
        default="127.0.0.1",
        help="IBKR TWS/Gateway host",
    )
    analyze.add_argument(
        "--ibkr-port",
        type=int,
        default=7497,
        help="IBKR TWS/Gateway port",
    )
    analyze.add_argument(
        "--sheets-id",
        default=None,
        help="Google Sheets ID for portfolio",
    )
    analyze.add_argument(
        "--credentials",
        default=None,
        help="Path to Google service account JSON",
    )
    analyze.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    # --- publish ---
    publish = sub.add_parser("publish", help="Publish a markdown report to Notion")
    publish.add_argument(
        "md_path",
        type=Path,
        help="Path to the markdown report file",
    )
    publish.add_argument(
        "--attach",
        type=Path,
        nargs="+",
        default=None,
        help="File(s) to attach to the Notion page (e.g. .pptx, .pdf)",
    )
    publish.add_argument(
        "--target",
        choices=["indepth-analysis", "jeg-report"],
        default="indepth-analysis",
        help="Notion publish target (default: indepth-analysis)",
    )
    publish.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    # --- update ---
    update = sub.add_parser("update", help="Scrape and download reports")
    update.add_argument(
        "source",
        choices=["kcif"],
        help="Report source to update",
    )
    update.add_argument("--year", type=int, default=None, help="Filter by year")
    update.add_argument("--month", type=int, default=None, help="Filter by month")
    update.add_argument("--limit", type=int, default=None, help="Max reports to scrape")
    update.add_argument(
        "--metadata-only",
        action="store_true",
        help="Catalog only, skip downloads",
    )
    update.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    # --- process ---
    process = sub.add_parser("process", help="Process downloaded PDFs")
    process.add_argument("--source", default=None, help="Process specific source only")
    process.add_argument(
        "--embedding-provider",
        choices=["local"],
        default="local",
        help="Embedding provider (default: local)",
    )
    process.add_argument(
        "--dry-run",
        action="store_true",
        help="Show estimates only, do not process",
    )
    process.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    # --- search ---
    search = sub.add_parser("search", help="Semantic search over reports")
    search.add_argument("query", help="Search query text")
    search.add_argument(
        "--top-k", type=int, default=5, help="Number of results (default: 5)"
    )
    search.add_argument(
        "--date-from", default=None, help="Filter: published after (YYYY-MM-DD)"
    )
    search.add_argument(
        "--date-to", default=None, help="Filter: published before (YYYY-MM-DD)"
    )
    search.add_argument("--source", default=None, help="Filter by source name")
    search.add_argument(
        "--embedding-provider",
        choices=["local"],
        default="local",
        help="Embedding provider for query (default: local)",
    )
    search.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    # --- status ---
    status = sub.add_parser("status", help="Show database status and cost summary")
    status.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    # --- report ---
    report = sub.add_parser("report", help="Generate research reports")
    report_sub = report.add_subparsers(dest="report_type")

    euro = report_sub.add_parser("euro-macro", help="Monthly European macro report")
    today = date.today()

    def _validate_year(v: str) -> int:
        y = int(v)
        if not 2000 <= y <= 2100:
            raise argparse.ArgumentTypeError("year must be 2000-2100")
        return y

    def _validate_month(v: str) -> int:
        m = int(v)
        if not 1 <= m <= 12:
            raise argparse.ArgumentTypeError("month must be 1-12")
        return m

    euro.add_argument(
        "--year", type=_validate_year, default=today.year, help="Report year"
    )
    euro.add_argument(
        "--month", type=_validate_month, default=today.month, help="Report month"
    )
    euro.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model for synthesis",
    )
    euro.add_argument(
        "--skip-update",
        action="store_true",
        help="Skip KCIF scrape/download",
    )
    euro.add_argument(
        "--collect-only",
        action="store_true",
        help="Run KCIF agent and save findings JSON (no synthesis)",
    )
    euro.add_argument(
        "--from-findings",
        type=str,
        default=None,
        metavar="PATH",
        help="Load findings JSON and synthesize report",
    )
    euro.add_argument(
        "--legacy-agents",
        action="store_true",
        help="Include broken httpx web agents (Media, Institutional, Data)",
    )
    euro.add_argument(
        "--slide",
        action="store_true",
        help="Generate one-page PowerPoint dashboard slide",
    )
    euro.add_argument(
        "--no-macro",
        action="store_true",
        help="Disable ForexFactory macro calendar (for offline use)",
    )
    euro.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass 4-hour cache for ForexFactory JSON feeds",
    )
    euro.add_argument(
        "--alert-abs-surprise",
        type=float,
        default=None,
        help=(
            "Send Telegram alert for any High-impact EUR/GBP release with "
            "abs surprise > threshold"
        ),
    )
    euro.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    # --- dev-welfare ---
    dw = report_sub.add_parser(
        "dev-welfare", help="Development & welfare report"
    )
    dw.add_argument(
        "--year", type=_validate_year, default=today.year, help="Report year"
    )
    dw.add_argument(
        "--month", type=_validate_month, default=today.month, help="Report month"
    )
    dw.add_argument(
        "--week", type=int, default=None, help="Week of month (1-5)"
    )
    dw.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model for synthesis",
    )
    dw.add_argument(
        "--type",
        dest="dw_report_type",
        choices=["weekly", "monthly"],
        default="weekly",
        help="Report type (weekly or monthly)",
    )
    dw.add_argument(
        "--collect-only",
        action="store_true",
        help="Run agents and save findings JSON (no synthesis)",
    )
    dw.add_argument(
        "--from-findings",
        type=str,
        default=None,
        metavar="PATH",
        help="Load findings JSON and synthesize report",
    )

    # --- issue-track ---
    it = report_sub.add_parser(
        "issue-track", help="Fast issue tracking and update report"
    )
    it.add_argument("--topic", type=str, required=True, help="Issue topic (natural language)")
    it.add_argument("--slug", type=str, default=None, help="Topic slug (auto-generated if omitted)")
    it.add_argument("--since", type=str, default=None, metavar="YYYY-MM-DD", help="Collect from date (default: 7 days ago)")
    it.add_argument("--model", default="claude-sonnet-4-6", help="Claude model for synthesis")
    it.add_argument("--tier-limit", type=int, default=4, choices=[1, 2, 3, 4], help="Max tier to collect (1=primary only … 4=all)")
    it.add_argument("--collect-only", action="store_true", help="Collect evidence only, skip synthesis")
    it.add_argument("--from-evidence", type=str, default=None, metavar="PATH", help="Synthesize from saved evidence JSON")
    it.add_argument("--publish", action="store_true", help="Publish report to Notion after generation")
    it.add_argument("--target", default="indepth-analysis", choices=["indepth-analysis", "jeg-report"], help="Notion publish target")

    # --- macro-backfill ---
    mb = sub.add_parser(
        "macro-backfill",
        help="Backfill ForexFactory historical weeks into local DB",
    )
    mb.add_argument(
        "--weeks", type=int, default=12, help="Number of weeks to backfill (default 12)"
    )
    mb.add_argument("--countries", default="EUR,GBP,CHF,SEK")
    mb.add_argument(
        "--min-impact", default="Medium", choices=["Low", "Medium", "High"]
    )
    mb.add_argument(
        "--db-path", type=Path, default=Path("data/macro_calendar.db")
    )
    mb.add_argument(
        "--rate-limit", type=float, default=5.0, help="Seconds between requests"
    )
    mb.add_argument(
        "--browser-cookie",
        default=None,
        help="Cookie string for Cloudflare bypass",
    )
    mb.add_argument("-v", "--verbose", action="store_true")

    # --- issue (list/show/search) ---
    issue_cmd = sub.add_parser("issue", help="Manage accumulated issue topics")
    issue_sub = issue_cmd.add_subparsers(dest="issue_action")

    issue_sub.add_parser("list", help="List all tracked issue topics")

    issue_show = issue_sub.add_parser("show", help="Show runs and stats for a topic")
    issue_show.add_argument("slug", help="Topic slug")

    issue_search = issue_sub.add_parser("search", help="Semantic search within a topic")
    issue_search.add_argument("slug", help="Topic slug")
    issue_search.add_argument("query", help="Search query")
    issue_search.add_argument("--n", type=int, default=10, help="Number of results")

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


def _run_analyze(args: argparse.Namespace) -> None:
    """Execute the analyze subcommand."""
    config = AnalysisConfig(
        ibkr_host=args.ibkr_host,
        ibkr_port=args.ibkr_port,
        sheets_id=args.sheets_id,
        credentials_path=args.credentials,
    )

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
            f"\n[green]Generated {len(chart_paths)} chart(s) in {charts_dir}[/green]"
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


def _run_publish(args: argparse.Namespace) -> None:
    """Execute the publish subcommand."""
    from dotenv import load_dotenv

    load_dotenv()

    target = getattr(args, "target", "indepth-analysis")
    _ENV_MAP = {
        "indepth-analysis": "NOTION_PAGE_ID_INDEPTH_ANALYSIS",
        "jeg-report": "NOTION_PAGE_ID_JEG_REPORT",
    }
    page_id_key = _ENV_MAP[target]

    token = os.environ.get("NOTION_TOKEN")
    parent_id = os.environ.get(page_id_key)

    if not token:
        console.print("[red]NOTION_TOKEN not set in environment or .env[/red]")
        sys.exit(1)
    if not parent_id:
        console.print(
            f"[red]{page_id_key} not set in environment or .env[/red]"
        )
        sys.exit(1)

    md_path: Path = args.md_path
    if not md_path.exists():
        console.print(f"[red]File not found: {md_path}[/red]")
        sys.exit(1)

    from indepth_analysis.output.notion_publisher import publish_to_notion

    attachments = getattr(args, "attach", None)

    with console.status("[cyan]Publishing report to Notion..."):
        url = publish_to_notion(md_path, token, parent_id, attachments=attachments)

    console.print(f"[green]Published to Notion:[/green] {url}")


def _run_update(args: argparse.Namespace) -> None:
    """Execute the update subcommand."""
    from indepth_analysis.config import ReferenceConfig
    from indepth_analysis.data.kcif_client import KCIFScraper, file_hash
    from indepth_analysis.data.scraper_base import ScraperResult
    from indepth_analysis.db import ReferenceDB
    from indepth_analysis.models.reference import (
        DownloadStatus,
        Report,
    )

    config = ReferenceConfig()
    db = ReferenceDB(Path(config.db_path))

    scrapers = {"kcif": KCIFScraper}

    scraper_cls = scrapers[args.source]
    scraper = scraper_cls()

    source = db.get_or_create_source(scraper.source_name, scraper.base_url)
    assert source.id is not None

    with console.status(f"[cyan]Scraping {args.source} catalog..."):
        results = scraper.scrape_listing(
            year=args.year, month=args.month, limit=args.limit
        )

    console.print(f"Found [green]{len(results)}[/green] reports")

    new_count = 0
    for r in results:
        report = Report(
            source_id=source.id,
            external_id=r.external_id,
            title=r.title,
            category=r.category,
            author=r.author,
            published_date=r.published_date,
            url=r.url,
            file_name=None,
        )
        report = db.upsert_report(report)
        if report.id and report.download_status == DownloadStatus.PENDING:
            new_count += 1

    console.print(f"New reports cataloged: [green]{new_count}[/green]")

    if args.metadata_only:
        console.print("[yellow]Metadata-only mode, skipping downloads.[/yellow]")
        db.update_source_scraped(source.id)
        db.close()
        scraper.close()
        return

    # Download pending reports
    dest_dir = Path(config.download_dir) / scraper.source_name
    pending = db.get_reports(
        source_id=source.id, download_status=DownloadStatus.PENDING
    )

    if not pending:
        console.print("No pending downloads.")
    else:
        downloaded = 0
        restricted = 0
        failed = 0

        for report in pending:
            assert report.id is not None
            sr = ScraperResult(
                external_id=report.external_id,
                title=report.title,
                category=report.category,
                author=report.author,
                published_date=report.published_date,
                url=report.url,
            )
            try:
                with console.status(f"[cyan]Downloading: {report.title[:50]}..."):
                    filepath = scraper.download_file(sr, dest_dir)

                if filepath is None:
                    db.update_report_download(
                        report.id, status=DownloadStatus.RESTRICTED
                    )
                    restricted += 1
                else:
                    fhash = file_hash(filepath)
                    db.update_report_download(
                        report.id,
                        status=DownloadStatus.DOWNLOADED,
                        file_name=filepath.name,
                        file_size_bytes=filepath.stat().st_size,
                        file_hash=fhash,
                    )
                    downloaded += 1
            except Exception as e:
                logger.warning("Download failed for %s: %s", report.title, e)
                db.update_report_download(
                    report.id,
                    status=DownloadStatus.FAILED,
                    error=str(e),
                )
                failed += 1

        console.print(
            f"Downloads: [green]{downloaded}[/green] OK, "
            f"[yellow]{restricted}[/yellow] restricted, "
            f"[red]{failed}[/red] failed"
        )

    db.update_source_scraped(source.id)
    db.close()
    scraper.close()


def _run_process(args: argparse.Namespace) -> None:
    """Execute the process subcommand."""
    from indepth_analysis.config import ReferenceConfig
    from indepth_analysis.db import ReferenceDB
    from indepth_analysis.models.reference import (
        DownloadStatus,
        ProcessingStatus,
    )
    from indepth_analysis.processing import process_reports

    config = ReferenceConfig()
    db = ReferenceDB(Path(config.db_path))

    # Get downloaded but unprocessed reports
    kwargs: dict = {"download_status": DownloadStatus.DOWNLOADED}
    if args.source:
        source = db.conn.execute(
            "SELECT id FROM sources WHERE LOWER(name) = LOWER(?)",
            (args.source,),
        ).fetchone()
        if not source:
            console.print(f"[red]Source '{args.source}' not found.[/red]")
            db.close()
            sys.exit(1)
        kwargs["source_id"] = source["id"]

    reports = db.get_reports(**kwargs)
    # Filter to those that still need processing
    reports = [
        r
        for r in reports
        if r.processing_status
        in (
            ProcessingStatus.UNPROCESSED,
            ProcessingStatus.EXTRACTED,
            ProcessingStatus.CHUNKED,
        )
    ]

    if not reports:
        console.print("No reports to process.")
        db.close()
        return

    if args.dry_run:
        console.print(f"[yellow]Dry run:[/yellow] {len(reports)} reports to process")
        total_pages = 0
        for r in reports:
            pages = r.page_count or 30  # estimate
            total_pages += pages
        console.print(f"Estimated pages: ~{total_pages}")
        console.print("Estimated cost: $0.00 (local embeddings)")
        db.close()
        return

    process_reports(reports, config, db, console)
    db.close()


def _run_search(args: argparse.Namespace) -> None:
    """Execute the search subcommand."""
    from indepth_analysis.config import ReferenceConfig
    from indepth_analysis.db import ReferenceDB
    from indepth_analysis.search.retriever import search_and_display

    config = ReferenceConfig()
    db = ReferenceDB(Path(config.db_path))

    search_and_display(
        query=args.query,
        db=db,
        config=config,
        console=console,
        top_k=args.top_k,
        date_from=args.date_from,
        date_to=args.date_to,
        source_filter=args.source,
    )
    db.close()


def _run_status(args: argparse.Namespace) -> None:
    """Execute the status subcommand."""
    from indepth_analysis.config import ReferenceConfig
    from indepth_analysis.db import ReferenceDB

    config = ReferenceConfig()
    db = ReferenceDB(Path(config.db_path))

    summary = db.get_status_summary()

    table = Table(title="Reference Database Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Sources", str(summary["sources"]))
    table.add_row("Total reports", str(summary["reports"]))
    table.add_row("Total chunks", str(summary["chunks"]))
    table.add_row("Embedded chunks", str(summary["embedded_chunks"]))

    console.print(table)

    # Download status breakdown
    if summary["download_status"]:
        dt = Table(title="Download Status")
        dt.add_column("Status", style="cyan")
        dt.add_column("Count", justify="right")
        for status, count in sorted(summary["download_status"].items()):
            dt.add_row(status, str(count))
        console.print(dt)

    # Processing status breakdown
    if summary["processing_status"]:
        pt = Table(title="Processing Status")
        pt.add_column("Status", style="cyan")
        pt.add_column("Count", justify="right")
        for status, count in sorted(summary["processing_status"].items()):
            pt.add_row(status, str(count))
        console.print(pt)

    # Cost summary
    costs = db.get_cost_summary()
    if costs:
        ct = Table(title="Cost Summary")
        ct.add_column("Source", style="cyan")
        ct.add_column("Total", justify="right")
        ct.add_column("Downloaded", justify="right")
        ct.add_column("Embedded", justify="right")
        ct.add_column("Cost (USD)", justify="right")
        for c in costs:
            ct.add_row(
                c["name"],
                str(c["total"]),
                str(c["downloaded"]),
                str(c["embedded"]),
                f"${c['total_cost']:.4f}" if c["total_cost"] else "$0.0000",
            )
        console.print(ct)

    db.close()


def _run_report(args: argparse.Namespace) -> None:
    """Execute the report subcommand."""
    from dotenv import load_dotenv

    load_dotenv()

    if args.report_type == "euro-macro":
        collect_only = getattr(args, "collect_only", False)
        from_findings = getattr(args, "from_findings", None)
        if collect_only and from_findings:
            console.print(
                "[red]--collect-only and --from-findings are mutually exclusive.[/red]"
            )
            sys.exit(1)

        from indepth_analysis.skills.euro_macro import run_euro_macro

        run_euro_macro(
            year=args.year,
            month=args.month,
            model=args.model,
            skip_update=args.skip_update,
            verbose=getattr(args, "verbose", False),
            collect_only=collect_only,
            from_findings=from_findings,
            legacy_agents=getattr(args, "legacy_agents", False),
            slide=getattr(args, "slide", False),
            no_macro=getattr(args, "no_macro", False),
            force_refresh=getattr(args, "force_refresh", False),
            alert_abs_surprise=getattr(args, "alert_abs_surprise", None),
        )
    elif args.report_type == "dev-welfare":
        collect_only = getattr(args, "collect_only", False)
        from_findings = getattr(args, "from_findings", None)
        if collect_only and from_findings:
            console.print(
                "[red]--collect-only and --from-findings are mutually exclusive.[/red]"
            )
            sys.exit(1)

        from indepth_analysis.skills.dev_welfare import run_dev_welfare

        run_dev_welfare(
            year=args.year,
            month=args.month,
            model=args.model,
            report_type=getattr(args, "dw_report_type", "weekly"),
            week=getattr(args, "week", None),
            collect_only=collect_only,
            from_findings=from_findings,
        )
    elif args.report_type == "issue-track":
        collect_only = getattr(args, "collect_only", False)
        from_evidence = getattr(args, "from_evidence", None)
        if collect_only and from_evidence:
            console.print(
                "[red]--collect-only and --from-evidence are mutually exclusive.[/red]"
            )
            sys.exit(1)

        from indepth_analysis.skills.issue_track import run_issue_track

        run_issue_track(
            topic=args.topic,
            slug=getattr(args, "slug", None),
            since=getattr(args, "since", None),
            model=args.model,
            collect_only=collect_only,
            from_evidence_path=from_evidence,
            tier_limit=getattr(args, "tier_limit", 4),
        )

        if getattr(args, "publish", False) and not collect_only:
            report_files = sorted(
                (Path("reports") / "issue_track" / (getattr(args, "slug") or "")).glob("*.md")
            ) if getattr(args, "slug") else []
            if report_files:
                from indepth_analysis.output.notion_publisher import NotionPublisher
                publisher = NotionPublisher()
                target = getattr(args, "target", "indepth-analysis")
                publisher.publish(report_files[-1], target=target)
                console.print(f"[green]Published to Notion ({target})[/green]")
    else:
        console.print(
            "[red]Unknown report type. Use 'euro-macro', 'dev-welfare', or 'issue-track'.[/red]"
        )
        sys.exit(1)


def _run_issue(args: argparse.Namespace) -> None:
    """Execute the issue subcommand (list/show/search)."""
    from dotenv import load_dotenv

    load_dotenv()

    from indepth_analysis.skills.issue_track.store import IssueStore

    action = getattr(args, "issue_action", None)
    if action is None:
        console.print("[yellow]Usage: issue {list|show|search}[/yellow]")
        return

    store = IssueStore()
    store.connect()

    if action == "list":
        topics = store.list_topics()
        if not topics:
            console.print("[yellow]No tracked topics yet.[/yellow]")
        else:
            from rich.table import Table as RichTable

            t = RichTable(title="Tracked Issue Topics")
            t.add_column("slug", style="cyan")
            t.add_column("title")
            t.add_column("last_run", justify="right")
            for row in topics:
                t.add_row(
                    row["slug"],
                    row["title"][:60],
                    (row["last_run_at"] or "—")[:16],
                )
            console.print(t)

    elif action == "show":
        slug = args.slug
        ev = store.get_evidence_for_slug(slug)
        run_count = store.get_run_count(slug)
        console.print(f"[cyan]{slug}[/cyan]: {run_count} runs, {len(ev)} evidence total")
        by_tier: dict[int, int] = {}
        for e in ev:
            by_tier[e.tier] = by_tier.get(e.tier, 0) + 1
        for tier, cnt in sorted(by_tier.items()):
            console.print(f"  Tier {tier}: {cnt} items")

    elif action == "search":
        results = store.semantic_search(args.slug, args.query, n_results=args.n)
        if not results:
            console.print("[yellow]No results (ChromaDB may not be available).[/yellow]")
        for i, r in enumerate(results, 1):
            meta = r.get("metadata", {})
            console.print(
                f"[{i}] [{meta.get('stance', '?')}] dist={r['distance']:.3f}\n"
                f"    {r['document'][:200]}\n"
                f"    {meta.get('canonical_url', '')}"
            )

    store.close()


KNOWN_COMMANDS = (
    "analyze",
    "publish",
    "update",
    "process",
    "search",
    "status",
    "report",
    "issue",
    "macro-backfill",
    "-h",
    "--help",
)


def _run_macro_backfill(args: argparse.Namespace) -> None:
    """Execute the macro-backfill subcommand."""
    from indepth_analysis.skills.euro_macro.macro_backfill import (
        backfill_history,
    )

    def progress(i: int, total: int, week) -> None:
        if args.verbose:
            print(f"  [{i}/{total}] {week}")

    countries = tuple(c.strip() for c in args.countries.split(",") if c.strip())
    report = backfill_history(
        weeks_back=args.weeks,
        db_path=args.db_path,
        countries=countries,
        min_impact=args.min_impact,
        rate_limit_seconds=args.rate_limit,
        browser_cookie=args.browser_cookie,
        progress=progress,
    )

    print(
        f"Backfill complete: {report.weeks_succeeded}/{report.weeks_requested} "
        f"weeks, {report.events_written} events written"
    )
    if report.waf_blocked:
        print(
            f"\nWAF blocked on {len(report.waf_blocked)} week(s): "
            f"{[str(w) for w in report.waf_blocked]}"
        )
        print(
            "To bypass: open https://www.forexfactory.com in your browser, "
            "complete the"
        )
        print(
            "Cloudflare challenge, then re-run with "
            '--browser-cookie="cf_clearance=..."'
        )
    if report.weeks_failed:
        print(f"Failed weeks: {[str(w) for w in report.weeks_failed]}")
    for note in report.notes:
        print(f"  note: {note}")


def main() -> None:
    parser = build_parser()

    # Backward compatibility: if first arg is not a known subcommand,
    # treat it as a ticker for the analyze subcommand
    if len(sys.argv) > 1 and sys.argv[1] not in KNOWN_COMMANDS:
        sys.argv.insert(1, "analyze")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    level = logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    try:
        if args.command == "analyze":
            _run_analyze(args)
        elif args.command == "publish":
            _run_publish(args)
        elif args.command == "update":
            _run_update(args)
        elif args.command == "process":
            _run_process(args)
        elif args.command == "search":
            _run_search(args)
        elif args.command == "status":
            _run_status(args)
        elif args.command == "report":
            _run_report(args)
        elif args.command == "issue":
            _run_issue(args)
        elif args.command == "macro-backfill":
            _run_macro_backfill(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
