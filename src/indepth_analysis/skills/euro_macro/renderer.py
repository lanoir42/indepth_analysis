"""Markdown report renderer and Rich console output."""

import logging
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from indepth_analysis.models.euro_macro import EuroMacroReport

logger = logging.getLogger(__name__)


def render_markdown(report: EuroMacroReport) -> str:
    """Render an EuroMacroReport to a markdown string."""
    lines: list[str] = []

    # Title
    lines.append(f"# {report.title}")
    lines.append("")

    # Table of contents
    lines.append("## 목차")
    for section in report.sections:
        anchor = section.heading.lower().replace(" ", "-")
        lines.append(f"- [{section.heading}](#{anchor})")
    lines.append("")

    # Sections
    for section in report.sections:
        lines.append(f"## {section.heading}")
        lines.append("")
        lines.append(section.content)
        lines.append("")

    # Source appendix
    lines.append("---")
    lines.append("")
    lines.append("## 참고 자료")
    lines.append("")
    for ar in report.agent_results:
        if not ar.findings:
            continue
        lines.append(f"### {ar.agent_name}")
        for f in ar.findings:
            date_str = f" ({f.published_date})" if f.published_date else ""
            url_str = f" — {f.source_url}" if f.source_url else ""
            lines.append(f"- {f.title}{date_str}{url_str}")
        lines.append("")

    # Metadata footer
    lines.append("---")
    lines.append("")
    lines.append(
        f"*생성일: {report.generated_at} | "
        f"모델: {report.model_used} | "
        f"수집 자료: {report.total_findings}건*"
    )
    lines.append("")

    return "\n".join(lines)


def save_report(report: EuroMacroReport, output_dir: str = "reports") -> Path:
    """Save the report to a markdown file and return the path."""
    dir_path = Path(output_dir) / "euro_macro"
    dir_path.mkdir(parents=True, exist_ok=True)

    filename = f"{report.year}-{report.month:02d}.md"
    filepath = dir_path / filename

    content = render_markdown(report)
    filepath.write_text(content, encoding="utf-8")
    return filepath


def print_summary(report: EuroMacroReport, console: Console) -> None:
    """Print a Rich summary of the report to the console."""
    console.print(Panel(f"[bold]{report.title}[/bold]", style="cyan"))

    # Agent results table
    table = Table(title="에이전트 수집 결과", show_header=True)
    table.add_column("에이전트", style="cyan")
    table.add_column("수집 건수", justify="right")
    table.add_column("검색 쿼리", justify="right")
    table.add_column("상태", style="green")

    for ar in report.agent_results:
        status = "[red]에러[/red]" if ar.error else "[green]완료[/green]"
        table.add_row(
            ar.agent_name,
            str(len(ar.findings)),
            str(len(ar.search_queries)),
            status,
        )

    console.print(table)

    # Section overview
    console.print(f"\n[bold]보고서 섹션 ({len(report.sections)}개):[/bold]")
    for section in report.sections:
        preview = section.content[:80].replace("\n", " ")
        console.print(f"  - {section.heading}: {preview}...")

    console.print(
        f"\n[dim]총 수집 자료: {report.total_findings}건 | "
        f"모델: {report.model_used}[/dim]"
    )
