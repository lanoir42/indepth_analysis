# ruff: noqa: E501
"""허브 문서 생성 — Briefing 앱 진입점(요약 + 연관 문서 절대경로 링크) + 저널 등록.

    M=indepth_analysis.skills.euro_macro.monthly_brief.hub
    uv run python -m $M --root reports/euro_macro/monthly_brief/2026-08 \
        --report-date 2026-09-14 --month 2026-08 [--register]

규격(Briefing 조사 결과): 다른 .md 문서 링크는 **절대경로**만 탭 가능, 상대경로·JSON 링크는
동작하지 않음 → JSON은 경로 텍스트로만 표기. PDF는 절대경로(≤8MB). 목차 `(#slug)`는 동작.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

PROJECT = Path("/Users/lanoir42/projects/indepth_analysis")


def _section(md: str, heading_prefix: str) -> str:
    """`## <heading_prefix>...` 절 본문(다음 `## `까지)."""
    lines = md.splitlines()
    out: list[str] = []
    on = False
    for ln in lines:
        if ln.startswith("## "):
            if on:
                break
            on = ln[3:].strip().startswith(heading_prefix)
            continue
        if on:
            out.append(ln)
    return "\n".join(out).strip()


def _slide_bullets(slide_md: str) -> str:
    """장표 본문(첫 `## ` 이전 또는 `## 발표자 노트` 이전)."""
    body = slide_md.split("\n## ")[0]
    return body.strip()


def build_hub(root: Path, report_date: str, month: str, phase: str = "spot") -> Path:
    y, m = month.split("-")
    files = {
        "report": root / f"{report_date}_europe_macro_{phase}_report.md",
        "explainer": root / f"{report_date}_europe_macro_{phase}_explainer.md",
        "slide": root / f"{report_date}_europe_macro_{phase}_slide.md",
    }
    delta = root / f"{report_date}_europe_macro_{phase}_delta.md"
    missing = [k for k, p in files.items() if not p.exists()]
    if missing:
        raise SystemExit(f"최종 파일 없음: {missing}")
    report = files["report"].read_text(encoding="utf-8")
    slide = files["slide"].read_text(encoding="utf-8")
    summary = _section(report, "요약") or _section(report, "Executive")
    abs_root = (PROJECT / root).resolve() if not root.is_absolute() else root
    data = abs_root / "data"
    bi_dir = PROJECT / "references" / "mendeley_europe" / month.replace("-", "")
    bi_pdfs = sorted(bi_dir.glob("*.pdf"))
    weekly = sorted((PROJECT / "references" / "mendeley_weekly").glob("*.pdf"))[-4:]
    slide_data = data / "slide_data.json"
    charts = []
    if slide_data.exists():
        try:
            charts = list(
                json.loads(slide_data.read_text("utf-8")).get("charts", {}).keys()
            )
        except json.JSONDecodeError:
            charts = []
    lines = [
        f"# [{phase.capitalize()}] {y}년 {int(m)}월 유럽 거시경제 월간 현황 허브 ({report_date})",
        "",
        f"> 팀 Noir 월간 브리프 v2 · 기준 시점 {report_date} 보고 · 대상 월 {y}-{m}",
        "> 입력: Bloomberg Intelligence(Mendeley `EUROPE {}`) · R&I 주간 덱 유럽 섹션 · KCIF · 웹 딥리서치(Sonnet 8축) · 로컬 백본".format(
            month.replace("-", "")
        ),
        "",
        "## 목차",
        "- [요약](#요약)",
        "- [장표 텍스트](#장표-텍스트)",
        "- [산출 문서](#산출-문서)",
        "- [데이터 파일](#데이터-파일)",
        "- [원문 자료](#원문-자료)",
        "",
        "## 요약",
        "",
        summary or "(요약 절을 찾지 못함 — 리포트 본문 참조)",
        "",
        "## 장표 텍스트",
        "",
        _slide_bullets(slide),
        "",
        "## 산출 문서",
        "",
        "단계 세트: preview(결정 전) → spot(결정 직후) → review(1~2주 후). 다른 단계 문서는 같은 폴더의 `*_europe_macro_{phase}_*.md`.",
        "",
        f"- 풀 리포트: [{files['report'].name}]({abs_root / files['report'].name})",
        f"- 해설서: [{files['explainer'].name}]({abs_root / files['explainer'].name})",
        f"- 장표 텍스트·발표자 노트: [{files['slide'].name}]({abs_root / files['slide'].name})",
        (
            f"- 변경 비교 리포트(이전 단계 대비): [{delta.name}]({abs_root / delta.name})"
            if delta.exists()
            else "- 변경 비교 리포트: (미생성 — Workflow의 Delta Report 단계 산출을 finalize_phase.sh 6번째 인자로 마감)"
        ),
        f"- 개발 계획서: `{abs_root / '00_dev_plan.md'}` (저널 스캔 제외 문서)",
        "",
        "## 데이터 파일",
        "",
        "Claude for PowerPoint 입력. Briefing 앱에서는 링크되지 않으므로 경로를 그대로 사용한다.",
        "",
        f"- 차트 시계열 전량: `{slide_data}`"
        + (f" — 차트 {len(charts)}개: {', '.join(charts)}" if charts else ""),
        f"- 장표 레이아웃 스펙: `{data / f'slide_spec_{phase}.json'}`",
        f"- 수치 정본: `{data / 'datapack.json'}` · 설명서 `{data / 'DATAPACK.md'}`",
        f"- 시계열 원자료: `{data}/series_S1_hicp.json`, `series_S2_activity.json`, `series_S3_rates_markets.json`, `series_S4_market_local.json`, `backbone_seed.json`",
        "",
        "## 원문 자료",
        "",
        f"- 리서치 원본(Sonnet 8축·BI 다이제스트·주간 덱 다이제스트·KCIF): `{abs_root / 'research'}/`",
        f"- Bloomberg Intelligence PDF {len(bi_pdfs)}건: `{bi_dir}/`",
    ]
    for p in bi_pdfs[:12]:
        lines.append(f"  - [{p.stem}]({p})")
    if len(bi_pdfs) > 12:
        lines.append(
            f"  - … 외 {len(bi_pdfs) - 12}건 (카탈로그: `{abs_root / 'research' / 'D1_bi_digest.md'}`)"
        )
    lines.append("- R&I 주간 덱(최근 4건):")
    for p in weekly:
        lines.append(f"  - [{p.stem}]({p})")
    lines += [
        "",
        f"- 전월 구판 리포트(KCIF 중심): [{PROJECT / 'reports/euro_macro' / f'{month}.md'}]({PROJECT / 'reports/euro_macro' / f'{month}.md'})",
        "",
        f"<!-- generated by monthly_brief.hub · {report_date} -->",
    ]
    dest = root / f"{report_date}_europe_macro_{phase}_index.md"
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def register(paths: list[Path]) -> None:
    for p in paths:
        subprocess.run(
            ["uv", "run", "briefing", "register", str(p.resolve())],
            cwd=Path.home() / "projects" / "orchestrator",
            check=False,
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--report-date", required=True)
    ap.add_argument("--month", required=True)
    ap.add_argument("--phase", default="spot", choices=["preview", "spot", "review"])
    ap.add_argument("--register", action="store_true")
    a = ap.parse_args()
    root = Path(a.root)
    hub = build_hub(root, a.report_date, a.month, a.phase)
    print(hub)
    if a.register:
        targets = [
            hub,
            root / f"{a.report_date}_europe_macro_{a.phase}_report.md",
            root / f"{a.report_date}_europe_macro_{a.phase}_explainer.md",
            root / f"{a.report_date}_europe_macro_{a.phase}_slide.md",
            root / f"{a.report_date}_europe_macro_{a.phase}_delta.md",
        ]
        register([t for t in targets if t.exists()])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
