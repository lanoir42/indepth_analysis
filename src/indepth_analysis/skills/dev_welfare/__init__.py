"""Development & Welfare report skill — entry point."""

import asyncio
from pathlib import Path

from rich.console import Console

from indepth_analysis.skills.dev_welfare.orchestrator import DevWelfareOrchestrator
from indepth_analysis.skills.dev_welfare.renderer import print_summary, save_report

console = Console()


def run_dev_welfare(
    year: int,
    month: int,
    model: str = "claude-sonnet-4-20250514",
    report_type: str = "weekly",
    week: int | None = None,
    collect_only: bool = False,
    from_findings: str | None = None,
) -> None:
    """Generate a development & welfare report.

    Modes:
        collect_only:   Run agents → save findings JSON → exit.
        from_findings:  Load findings JSON → synthesize → render report.
        (default):      End-to-end pipeline.
    """
    if collect_only:
        orchestrator = DevWelfareOrchestrator()
        with console.status("[cyan]리서치 에이전트 실행 중..."):
            agent_results = asyncio.run(orchestrator.collect(year, month))
        dest = DevWelfareOrchestrator.save_findings(
            agent_results, year, month, week=week
        )
        total = sum(len(ar.findings) for ar in agent_results)
        console.print(f"[green]수집 완료: {total}건 → {dest}[/green]")
        return

    if from_findings:
        orchestrator = DevWelfareOrchestrator()
        findings_path = Path(from_findings)
        if not findings_path.exists():
            console.print(f"[red]파일 없음: {findings_path}[/red]")
            raise SystemExit(1)
        agent_results, f_year, f_month, f_week = (
            DevWelfareOrchestrator.load_findings(findings_path)
        )
        console.print(
            f"[cyan]Loaded {sum(len(ar.findings) for ar in agent_results)} "
            f"findings from {findings_path}[/cyan]"
        )
        with console.status("[cyan]Claude CLI 합성 중..."):
            report = orchestrator.synthesize_from_findings(
                agent_results,
                f_year,
                f_month,
                model,
                report_type,
                f_week,
            )
        print_summary(report, console)
        filepath = save_report(report)
        console.print(f"\n[green]보고서 저장: {filepath}[/green]")
        return

    # Default: end-to-end pipeline
    orchestrator = DevWelfareOrchestrator()
    with console.status("[cyan]리서치 에이전트 실행 중..."):
        report = asyncio.run(
            orchestrator.run(
                year=year,
                month=month,
                model=model,
                report_type=report_type,
                week=week,
            )
        )

    print_summary(report, console)
    filepath = save_report(report)
    console.print(f"\n[green]보고서 저장: {filepath}[/green]")
