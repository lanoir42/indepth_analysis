"""Monthly brief sub-skill — 월간 유럽 매크로 현황 리포트.

산출: 풀 리포트 + 해설서 + 장표 텍스트 + 데이터 JSON.
Mendeley `EUROPE YYYYMM`(Bloomberg Intelligence) + `WEEKLY` 유럽 섹션 인덱스 +
백본 시계열 + Sonnet 웹리서치를 입력으로, 팀 Noir(Opus) 파이프라인이 산출물을 만든다.
"""

from __future__ import annotations

__version__ = "2.1.0"

import asyncio
import json
from datetime import date
from pathlib import Path


def run_stages(
    month: str,
    as_of: str | None,
    stages: list[str],
    axes: list[str] | None,
    root: str | None,
) -> None:
    """결정론·Sonnet 단계 실행기. Opus 단계(Advisor~Final)는 팀 Noir Workflow가 담당."""
    from rich.console import Console

    from indepth_analysis.skills.euro_macro.monthly_brief import backbone, research
    from indepth_analysis.skills.euro_macro.monthly_brief import sources as src

    console = Console()
    as_of = as_of or date.today().isoformat()
    root_p = Path(root) if root else Path("reports/euro_macro/monthly_brief") / month
    root_p.mkdir(parents=True, exist_ok=True)
    yyyymm = month.replace("-", "")
    if "fetch" in stages:
        console.print(f"[cyan]Mendeley EUROPE {yyyymm} 수집…[/cyan]")
        src.fetch_folder(f"EUROPE {yyyymm}", src.EUROPE_DIR / yyyymm)
        console.print("[cyan]Mendeley WEEKLY 수집·유럽 섹션 인덱스…[/cyan]")
        src.fetch_folder(
            "WEEKLY", src.WEEKLY_DIR, title_filter=lambda t: "거시경제_동향" in t
        )
        n = src.index_weekly_europe()
        console.print(f"[green]weekly_europe_sections +{n}[/green]")
    if "backbone" in stages:
        seed = backbone.build(root_p, month, as_of)
        (root_p / "data").mkdir(exist_ok=True)
        (root_p / "data" / "backbone_seed.json").write_text(
            json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        console.print("[green]backbone_seed.json 저장[/green]")
    if "market" in stages:
        from indepth_analysis.skills.euro_macro.monthly_brief import market_data

        md = market_data.build(f"{int(month[:4]) - 2}-01-01", as_of)
        (root_p / "data" / "series_S4_market_local.json").write_text(
            json.dumps(md, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        n_s = len(md["series"])
        console.print(f"[green]series_S4_market_local.json ({n_s})[/green]")
    run_axes = axes if axes is not None else list(research.pr.RESEARCH_AXES)
    if "research" in stages or "series" in stages:
        res = asyncio.run(
            research.run(
                root_p,
                month,
                as_of,
                [a for a in run_axes] if "research" in stages else [],
                list(research.pr.SERIES_AGENTS) if "series" in stages else [],
                None,
            )
        )
        console.print(f"[green]research/series 완료: {res}[/green]")
