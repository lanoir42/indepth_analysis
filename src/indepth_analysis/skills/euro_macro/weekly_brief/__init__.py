"""Weekly brief sub-skill — entry point.

Generates a weekly European macroeconomic brief slide (Korean 개조식 text +
JSON chart data) and optionally publishes the combined markdown to Notion.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

from rich.console import Console

from indepth_analysis.skills.euro_macro.weekly_brief.orchestrator import (
    WeeklyBriefOrchestrator,
)

logger = logging.getLogger(__name__)
console = Console()


def _try_download_mendeley_ref(date_str: str) -> Path | None:
    """Best-effort Mendeley WEEKLY PDF download. Returns path or None silently."""
    try:
        from indepth_analysis.data.mendeley_client import (
            download_latest_weekly_pdf,
        )
    except Exception as exc:
        logger.warning("Mendeley client import failed: %s", exc)
        return None

    dest_dir = Path("references") / "mendeley_weekly"
    try:
        path = download_latest_weekly_pdf(dest_dir=dest_dir, folder_name="WEEKLY")
        if path:
            console.print(f"[cyan]Mendeley WEEKLY 참고문서 저장: {path}[/cyan]")
        return path
    except Exception as exc:
        logger.warning("Mendeley download failed (non-fatal): %s", exc)
        return None


def run_weekly_brief(
    date_str: str | None = None,
    model: str = "claude-opus-4-20250514",
    no_evaluator: bool = False,
    publish: bool = True,
) -> None:
    """Generate weekly European macro brief slide + optional Notion publish.

    Args:
        date_str: "YYYY-MM-DD" report date. Defaults to today.
        model: Claude model id for synthesis/evaluator/R2.
        no_evaluator: Skip evaluator + Generator R2 stages.
        publish: Publish the combined markdown to Notion (indepth-analysis target).
    """
    if not date_str:
        date_str = date.today().isoformat()

    console.print(
        f"[cyan]주간 유럽 거시 브리프 생성 시작 — date={date_str}, model={model}[/cyan]"
    )

    # Optional Mendeley reference download (silent if creds missing).
    _try_download_mendeley_ref(date_str)

    orchestrator = WeeklyBriefOrchestrator(
        model=model, no_evaluator=no_evaluator
    )

    with console.status("[cyan]에이전트·합성·평가 파이프라인 실행 중..."):
        result = orchestrator.run(date_str)

    console.print(
        f"[green]슬라이드 텍스트 저장: {result.extra_paths['slide_text']}[/green]"
    )
    console.print(
        f"[green]차트 JSON 저장:    {result.extra_paths['slide_json']}[/green]"
    )
    console.print(f"[green]통합 마크다운 저장: {result.combined_path}[/green]")

    if result.high_issues.strip() and result.high_issues.strip() != "(없음)":
        console.print("[yellow]Evaluator HIGH 이슈 (적용 시도됨):[/yellow]")
        console.print(result.high_issues)
    if result.medium_issues.strip() and result.medium_issues.strip() != "(없음)":
        console.print("[yellow]Evaluator MEDIUM 이슈 (참고):[/yellow]")
        console.print(result.medium_issues)

    if not publish:
        return

    # Publish to Notion (indepth-analysis target).
    from dotenv import load_dotenv

    load_dotenv()

    token = os.environ.get("NOTION_TOKEN")
    parent_id = os.environ.get("NOTION_PAGE_ID_INDEPTH_ANALYSIS")

    if not token or not parent_id:
        console.print(
            "[yellow]NOTION_TOKEN 또는 NOTION_PAGE_ID_INDEPTH_ANALYSIS 미설정 "
            "— Notion 퍼블리시 건너뜀[/yellow]"
        )
        return

    try:
        from indepth_analysis.output.notion_publisher import publish_to_notion

        with console.status("[cyan]Notion 퍼블리시 중..."):
            url = publish_to_notion(result.combined_path, token, parent_id)
        console.print(f"[green]Notion 퍼블리시 완료: {url}[/green]")
    except Exception as exc:
        console.print(f"[red]Notion 퍼블리시 실패 (보고서는 저장됨): {exc}[/red]")
        if logger.isEnabledFor(logging.DEBUG):
            import traceback

            traceback.print_exc()
        # Non-fatal: don't sys.exit so caller still gets a saved report.
        return


__all__ = ["run_weekly_brief", "WeeklyBriefOrchestrator"]


if __name__ == "__main__":  # pragma: no cover
    # Allow `python -m indepth_analysis.skills.euro_macro.weekly_brief YYYY-MM-DD`
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_weekly_brief(date_str=arg)
