"""Euro-macro masterclass (월간 해설서) sub-skill — entry point.

Generates the monthly "유럽 매크로 마스터클래스 제N강" lecture from the
deterministic context pack (Stage 1, TE1) plus three Claude CLI writing calls,
evaluates it, and optionally publishes the markdown to Notion.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

DEFAULT_MODEL = "claude-opus-4-8"


def run_masterclass(
    year: int | None = None,
    month: int | None = None,
    model: str = DEFAULT_MODEL,
    skip_evaluator: bool = False,
    publish: bool = False,
    reports_dir: Path | str = Path("reports"),
):
    """Generate the monthly masterclass lecture (+ optional Notion publish).

    Args:
        year: Report year. Defaults to the current year.
        month: Report month. Defaults to the current month.
        model: Claude model id for topic selection / writing / evaluation.
        skip_evaluator: Skip the evaluator and the R2 revision round.
        publish: Publish the saved markdown to the ``indepth-analysis`` Notion
            page (same path the ``indepth publish`` CLI uses).
        reports_dir: Root reports directory.

    Returns:
        The :class:`MasterclassResult` for the run.
    """
    from indepth_analysis.skills.euro_macro.masterclass.orchestrator import (
        MasterclassOrchestrator,
    )

    today = date.today()
    year = year or today.year
    month = month or today.month

    console.print(
        f"[cyan]유럽 매크로 마스터클래스 생성 시작 — {year}-{month:02d}, "
        f"model={model}[/cyan]"
    )

    orchestrator = MasterclassOrchestrator(
        year,
        month,
        model=model,
        reports_dir=reports_dir,
        skip_evaluator=skip_evaluator,
    )
    result = orchestrator.run()

    console.print(
        f"[green]제{result.lecture_no}강 저장: {result.report_path} "
        f"({result.char_count:,}자)[/green]"
    )
    placeholders = [n for n, s in result.chapter_status.items() if s == "placeholder"]
    if placeholders:
        console.print(
            f"[yellow]자리표시자 장: {sorted(placeholders)} — 재생성 필요[/yellow]"
        )
    if result.high_issues:
        console.print(
            f"[yellow]Evaluator HIGH {len(result.high_issues)}건 "
            f"(R2 {'적용됨' if result.revised else '미적용'})[/yellow]"
        )
    for kind, items in result.gate_findings.items():
        if items:
            console.print(
                f"[yellow]{kind} 게이트 advisory {len(items)}건 "
                f"(발행 차단 없음)[/yellow]"
            )

    if publish:
        _publish(result.report_path)

    return result


def _publish(md_path: Path) -> None:
    """Publish the lecture markdown to the indepth-analysis Notion page."""
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
            url = publish_to_notion(md_path, token, parent_id)
        console.print(f"[green]Notion 퍼블리시 완료: {url}[/green]")
    except Exception as exc:  # noqa: BLE001 — report is already saved
        console.print(f"[red]Notion 퍼블리시 실패 (해설서는 저장됨): {exc}[/red]")


__all__ = ["DEFAULT_MODEL", "run_masterclass"]
