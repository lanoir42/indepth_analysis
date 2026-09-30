"""Monthly brief sub-skill — 월간 유럽 매크로 현황 리포트 (v3).

산출(단계 preview·interim·final마다): 풀 리포트 + 해설본 + 허브 + 차트/표 팩(JSON·CSV).
입력: Mendeley `EUROPE YYYYMM`(Bloomberg Intelligence) 문서 카드·그룹 섹션, 1차 통계
결정론 수집(Eurostat·ECB·시장), Sonnet 웹리서치 12축 + 웹 시계열, 주간 덱 유럽 인덱스.
Opus 단계는 `workflow/noir_v3.js`(Claude Code Workflow)가 담당한다.
설계: docs/euro_macro_monthly_brief/V3_PLAN.md · V3_CONTRACTS.md · MANUAL.md
"""

from __future__ import annotations

__version__ = "3.0.0"

import subprocess
import sys
from pathlib import Path

PKG = "indepth_analysis.skills.euro_macro.monthly_brief"
STAGES = ("fetch", "intake", "cards", "data", "research", "workflow-args")


def _run(module: str, *argv: str) -> int:
    cmd = [sys.executable, "-m", f"{PKG}.{module}", *argv]
    print("$", " ".join(cmd[2:]))
    return subprocess.run(cmd, check=False).returncode


def run_stages(
    month: str,
    as_of: str | None,
    stages: list[str],
    axes: list[str] | None,
    root: str | None,
    phase: str = "preview",
    report_date: str | None = None,
    web: list[str] | None = None,
) -> None:
    """결정론·Sonnet 단계 실행기(v3). 각 단계는 모듈 CLI를 호출하며 멱등이다."""
    from rich.console import Console

    from indepth_analysis.skills.euro_macro.monthly_brief import sources as src
    from indepth_analysis.skills.euro_macro.monthly_brief.edition import (
        BASE_DIR,
        load_edition,
    )

    console = Console()
    root_p = Path(root) if root else BASE_DIR / month
    ed_file = root_p / "edition.json"
    if not ed_file.exists():
        if not (as_of and report_date):
            raise SystemExit(
                "edition.json 없음 — --as-of·--report-date를 주거나 "
                "`python -m ...monthly_brief.edition init`으로 생성"
            )
        _run(
            "edition",
            "init",
            "--month",
            month,
            "--phase",
            phase,
            "--as-of",
            as_of,
            "--report-date",
            report_date,
            "--root",
            str(root_p),
        )
    ed = load_edition(root_p)
    r = str(root_p)
    rc: dict[str, int] = {}
    if "fetch" in stages:
        console.print(f"[cyan]Mendeley {ed.collection} + WEEKLY 수집…[/cyan]")
        src.fetch_folder(ed.collection, src.EUROPE_DIR / ed.yyyymm)
        src.fetch_folder(
            "WEEKLY", src.WEEKLY_DIR, title_filter=lambda t: "거시경제_동향" in t
        )
        console.print(f"weekly_europe_sections +{src.index_weekly_europe()}")
    if "intake" in stages:
        rc["intake"] = _run("intake", "scaffold", "--month", month, "--root", r)
    if "cards" in stages:
        rc["cards"] = _run("cards", "run", "--month", month, "--root", r)
        rc["intake2"] = _run("intake", "scaffold", "--month", month, "--root", r)
    if "data" in stages:
        rc["store"] = _run("datastore.store", "build", "--root", r, "--as-of", ed.as_of)
        rc["chart_pack"] = _run("chart_pack", "build", "--root", r)
        rc["validate"] = _run("validate_pack", "--root", r)
    if "research" in stages:
        # 축 미지정 시 12축 + 웹 시계열 2종 전량
        argv = ["--root", r, "--axes", *(axes or [f"R{i:02d}" for i in range(1, 13)])]
        if web is None and axes is None:
            web = ["W1", "W2"]
        if web:
            argv += ["--web", *web]
        rc["research"] = _run("research", *argv)
    if "workflow-args" in stages:
        rc["workflow-args"] = _run("workflow.args", "--root", r, "--write")
    console.print(f"[green]완료: {rc}[/green]")
    bad = {k: v for k, v in rc.items() if v}
    if bad:
        console.print(f"[yellow]비정상 종료: {bad}[/yellow]")
