"""Issue Track skill — fast issue tracking and update report generation."""

from pathlib import Path

from indepth_analysis.skills.issue_track.orchestrator import IssueTrackOrchestrator
from indepth_analysis.skills.issue_track.store import IssueStore


def run_issue_track(
    topic: str,
    slug: str | None = None,
    since: str | None = None,
    model: str = "claude-sonnet-4-6",
    collect_only: bool = False,
    from_evidence_path: str | None = None,
    tier_limit: int = 4,
    output_base: Path | None = None,
) -> None:
    """Entry point for the issue-track CLI command."""
    from rich.console import Console

    console = Console()

    from_evidence = None
    if from_evidence_path:
        import json

        data = json.loads(Path(from_evidence_path).read_text())
        from indepth_analysis.models.issue_track import Evidence

        from_evidence = [Evidence(**item) for item in data]

    store = IssueStore()
    orchestrator = IssueTrackOrchestrator(store=store, tier_limit=tier_limit)

    console.print(f"[cyan]Issue Track:[/cyan] {topic}")
    if slug:
        console.print(f"  slug: {slug}")
    console.print(f"  since: {since or '7일 전'}, tier_limit: {tier_limit}")
    console.print("")

    report = orchestrator.run(
        topic=topic,
        slug=slug,
        since=since,
        model=model,
        collect_only=collect_only,
        from_evidence=from_evidence,
        output_base=output_base,
    )

    if collect_only:
        console.print(
            f"[green]수집 완료:[/green] {report.run.new_evidence}건 신규 "
            f"(누적 {report.run.total_evidence}건)"
        )
    else:
        console.print(
            f"[green]보고서 생성:[/green] {report.run.report_path}"
        )
        console.print(
            f"  신규 evidence: {report.run.new_evidence}건 / "
            f"누적: {report.run.total_evidence}건"
        )
