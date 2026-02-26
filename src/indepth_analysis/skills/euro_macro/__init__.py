"""Euro Macro report skill — entry point."""

import asyncio
import os
from pathlib import Path

from rich.console import Console

from indepth_analysis.config import ReferenceConfig
from indepth_analysis.skills.euro_macro.orchestrator import EuroMacroOrchestrator
from indepth_analysis.skills.euro_macro.renderer import (
    print_summary,
    save_report,
)

console = Console()


def run_euro_macro(
    year: int,
    month: int,
    model: str = "claude-sonnet-4-20250514",
    skip_update: bool = False,
    verbose: bool = False,
    collect_only: bool = False,
    from_findings: str | None = None,
    legacy_agents: bool = False,
) -> None:
    """Generate a monthly European macroeconomic report.

    Modes:
        collect_only:   Run KCIF agent → save findings JSON → exit.
        from_findings:  Load findings JSON → synthesize → render report.
        (default):      End-to-end pipeline (KCIF-only by default).
    """
    config = ReferenceConfig()

    if collect_only:
        # Phase 1: collect only — no API key needed
        orchestrator = EuroMacroOrchestrator(config, legacy_agents=legacy_agents)
        with console.status("[cyan]리서치 에이전트 실행 중..."):
            agent_results = asyncio.run(
                orchestrator.collect(year, month, skip_update=skip_update)
            )
        dest = EuroMacroOrchestrator.save_findings(agent_results, year, month)
        total = sum(len(ar.findings) for ar in agent_results)
        console.print(f"[green]수집 완료: {total}건 → {dest}[/green]")
        return

    if from_findings:
        # Phase 3: synthesize from pre-collected findings
        anthropic_key = _require_api_key()
        orchestrator = EuroMacroOrchestrator(config, anthropic_key)
        findings_path = Path(from_findings)
        if not findings_path.exists():
            console.print(f"[red]파일 없음: {findings_path}[/red]")
            raise SystemExit(1)
        agent_results, f_year, f_month = EuroMacroOrchestrator.load_findings(
            findings_path
        )
        console.print(
            f"[cyan]Loaded {sum(len(ar.findings) for ar in agent_results)} "
            f"findings from {findings_path}[/cyan]"
        )
        with console.status("[cyan]Claude API 합성 중..."):
            report = orchestrator.synthesize_from_findings(
                agent_results, f_year, f_month, model
            )
        print_summary(report, console)
        filepath = save_report(report)
        console.print(f"\n[green]보고서 저장: {filepath}[/green]")
        return

    # Default: end-to-end pipeline (backward compatible)
    anthropic_key = _require_api_key()
    orchestrator = EuroMacroOrchestrator(
        config, anthropic_key, legacy_agents=legacy_agents
    )

    with console.status("[cyan]리서치 에이전트 실행 중..."):
        report = asyncio.run(
            orchestrator.run(
                year=year,
                month=month,
                model=model,
                skip_update=skip_update,
            )
        )

    print_summary(report, console)
    filepath = save_report(report)
    console.print(f"\n[green]보고서 저장: {filepath}[/green]")


def _require_api_key() -> str:
    """Get ANTHROPIC_API_KEY or exit."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        console.print(
            "[red]ANTHROPIC_API_KEY not set in environment. "
            "Set it via .env or export.[/red]"
        )
        raise SystemExit(1)
    return key
