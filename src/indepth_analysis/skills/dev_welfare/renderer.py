"""Markdown report renderer and Rich console output for dev_welfare."""

import logging
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from indepth_analysis.models.dev_welfare import DevWelfareReport

logger = logging.getLogger(__name__)


def render_markdown(report: DevWelfareReport) -> str:
    """Render a DevWelfareReport to a markdown string."""
    lines: list[str] = []

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

    # Source appendix — table per agent
    lines.append("---")
    lines.append("")
    lines.append("## 참고 자료")
    lines.append("")
    for ar in report.agent_results:
        if not ar.findings:
            continue
        lines.append(f"### {ar.agent_name}")
        lines.append("")
        lines.append("| 날짜 | 제목 | 내용 요약 | 링크 |")
        lines.append("|------|------|----------|------|")
        for f in ar.findings:
            date_str = f.published_date or "-"
            title = f.title.replace("|", "\\|")
            summary = (f.summary or "-").replace("|", "\\|").replace("\n", " ")
            if len(summary) > 120:
                summary = summary[:117] + "..."
            link = f"[링크]({f.source_url})" if f.source_url else "-"
            lines.append(f"| {date_str} | {title} | {summary} | {link} |")
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


def _report_filename(report: DevWelfareReport) -> str:
    if report.report_type == "weekly" and report.week is not None:
        return f"{report.year}-{report.month:02d}-W{report.week}.md"
    return f"{report.year}-{report.month:02d}.md"


def save_report(
    report: DevWelfareReport, output_dir: str = "reports"
) -> Path:
    """Save the report to a markdown file and return the path."""
    dir_path = Path(output_dir) / "dev_welfare"
    dir_path.mkdir(parents=True, exist_ok=True)

    filepath = dir_path / _report_filename(report)
    content = render_markdown(report)
    filepath.write_text(content, encoding="utf-8")
    return filepath


def print_summary(report: DevWelfareReport, console: Console) -> None:
    """Print a Rich summary of the report to the console."""
    console.print(Panel(f"[bold]{report.title}[/bold]", style="cyan"))

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

    console.print(f"\n[bold]보고서 섹션 ({len(report.sections)}개):[/bold]")
    for section in report.sections:
        preview = section.content[:80].replace("\n", " ")
        console.print(f"  - {section.heading}: {preview}...")

    console.print(
        f"\n[dim]총 수집 자료: {report.total_findings}건 | "
        f"모델: {report.model_used}[/dim]"
    )
