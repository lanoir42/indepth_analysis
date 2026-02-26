import logging

import numpy as np
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from indepth_analysis.config import ReferenceConfig
from indepth_analysis.db import ReferenceDB
from indepth_analysis.processing.embedder import get_embedder
from indepth_analysis.search.indexer import SearchIndex

logger = logging.getLogger(__name__)


def search_and_display(
    query: str,
    db: ReferenceDB,
    config: ReferenceConfig,
    console: Console,
    top_k: int = 5,
    date_from: str | None = None,
    date_to: str | None = None,
    source_filter: str | None = None,
) -> None:
    """Execute semantic search and display results with Rich formatting."""
    # Build index
    with console.status("[cyan]Loading search index..."):
        index = SearchIndex()
        index.build(db)

    if index.size == 0:
        console.print(
            "[yellow]No embedded documents in database. "
            "Run 'indepth process' first.[/yellow]"
        )
        return

    # Apply filters to get valid report IDs
    report_id_filter = _build_report_filter(db, date_from, date_to, source_filter)

    # Embed query
    with console.status("[cyan]Embedding query..."):
        embedder = get_embedder(config.embedding_provider, config)
        query_bytes = embedder.embed(query)
        query_vec = np.frombuffer(query_bytes, dtype=np.float32)

    # Search
    results = index.search(query_vec, top_k=top_k, report_id_filter=report_id_filter)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    # Display
    console.print(Panel(f"[bold]Search:[/bold] {query}", style="cyan"))

    table = Table(show_header=True, show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Report", style="cyan", max_width=40)
    table.add_column("Pages", width=8)
    table.add_column("Excerpt", max_width=60)

    for rank, (chunk, score) in enumerate(results, 1):
        # Fetch report title
        report = db.get_report_by_id(chunk.report_id)
        title = report.title[:38] if report else f"Report #{chunk.report_id}"
        date_str = report.published_date or "" if report else ""
        if date_str:
            title = f"{title}\n[dim]{date_str}[/dim]"

        # Page range
        pages = ""
        if chunk.page_start and chunk.page_end:
            if chunk.page_start == chunk.page_end:
                pages = f"p.{chunk.page_start}"
            else:
                pages = f"p.{chunk.page_start}-{chunk.page_end}"

        # Excerpt (first 150 chars)
        excerpt = chunk.content[:150].replace("\n", " ")
        if len(chunk.content) > 150:
            excerpt += "..."

        # Score coloring
        score_text = Text(f"{score:.3f}")
        if score >= 0.7:
            score_text.stylize("bold green")
        elif score >= 0.5:
            score_text.stylize("green")
        elif score >= 0.3:
            score_text.stylize("yellow")
        else:
            score_text.stylize("dim")

        table.add_row(str(rank), score_text, title, pages, excerpt)

    console.print(table)
    console.print(f"\n[dim]Showing top {len(results)} of {index.size} chunks[/dim]")


def _build_report_filter(
    db: ReferenceDB,
    date_from: str | None,
    date_to: str | None,
    source_filter: str | None,
) -> set[int] | None:
    """Build a set of report IDs matching the given filters."""
    if not date_from and not date_to and not source_filter:
        return None

    query = "SELECT r.id FROM reports r JOIN sources s ON r.source_id = s.id WHERE 1=1"
    params: list = []

    if date_from:
        query += " AND r.published_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND r.published_date <= ?"
        params.append(date_to)
    if source_filter:
        query += " AND LOWER(s.name) = LOWER(?)"
        params.append(source_filter)

    rows = db.conn.execute(query, params).fetchall()
    return {r["id"] for r in rows}
