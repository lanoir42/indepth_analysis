# ruff: noqa: E501
"""v3 마감 — 결정론 게이트·최종본 확정·허브·session.json 단계 기록·등록.

    M=indepth_analysis.skills.euro_macro.monthly_brief.finalize
    uv run python -m $M gate --root ROOT --file drafts/preview_report_r3.md --kind report
    uv run python -m $M promote --root ROOT --report preview_report_r3 \
        --explainer preview_explainer_r3 [--register]

게이트(차단 = FAIL): 본문 금지 토큰(파이프라인 용어·조사 라벨·거부 문장), 문체 금지어,
상대 날짜, `lint-temporal` HIGH, 존재하지 않는 차트·표 참조, H1 단계 태그.
자문(WARN): `A가 아니라 B` 계열 과다, 분량 목표 이탈, `lint-numeric` HIGH, 장별 분량.
`_editorial/`·참고문헌 절은 금지 토큰 검사에서 제외한다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from indepth_analysis.skills.euro_macro.monthly_brief.edition import (
    PHASE_KO,
    PHASES,
    Edition,
    load_edition,
)

PROJECT = Path("/Users/lanoir42/projects/indepth_analysis")

# --- 금지 토큰 (V3_CONTRACTS §5) -------------------------------------------
BANNED_LITERALS = [
    "정본",
    "DATAPACK",
    "datapack",
    "§",
    "팀 Noir",
    "Advisor",
    "Quant",
    "Chief",
    "Polish",
    "채점",
    "본 단계",
    "본 회차",
    "본 문서",
    "등재",
    "[확정]",
    "[보도]",
    "[추정]",
    "[시장]",
    "[미확인]",
    "확인되지 않아",
    "관측 대상에서 제외",
    "인용하지 않는다",
    "산출하지 않는다",
    "NUMBERS.md",
    "facts.md",
    "series_store",
]
# 소문자 단계명은 파이프라인 용어로만 쓰인다(BI 원제 PREVIEW 등 대문자는 허용).
BANNED_REGEX = [
    r"\b(preview|spot|review|interim)\b",
    r"(?<![A-Za-z0-9])[NSDRW]\d{1,2}(?![0-9A-Za-z])",
    r"\bBI-?\d+\b",
    r"\b[PSR]D-\d+\b",
    r"감사(?:자|에서|결과|라운드| 라운드)",
]
STYLE_BANNED = [
    "은폐",
    "자초",
    "딱 ",
    "결코",
    "압도적",
    "게임체인저",
    "혁명적",
    "폭발적",
    "우리가",
    "우리는",
    "필자",
    "이 리포트는",
    "본 리포트는",
    "이 보고서는",
    "본 보고서는",
    "하는 것이다",
    "라는 것이다",
    "다름 아니",
    "수밖에 없",
    "에 있어서",
    "와 관련하여",
]
RELATIVE_DATES = (
    r"(?<![가-힣])(?:어제|내일|지난달|이번 주|지난주|다음 주|이번 달|다음 달)"
    r"|올해 들어|최근 며칠"
)
ANIRA = r"(?:가|이) 아니(?:라|고)"
CHART_REF = re.compile(r"\[(차트|표):\s*([A-Za-z0-9_\-]+)\]")
EXEMPT_HEADINGS = ("참고문헌", "참고 문헌", "자료 목록", "출처")


def _body_lines(md: str) -> list[tuple[int, str]]:
    """검사 대상 줄(H1·참고문헌 절 제외, 코드펜스 제외)."""
    out: list[tuple[int, str]] = []
    exempt = False
    fence = False
    for i, ln in enumerate(md.splitlines(), 1):
        if ln.startswith("```"):
            fence = not fence
            continue
        if fence or ln.startswith("# "):
            continue
        if ln.startswith("## ") or ln.startswith("### "):
            exempt = any(h in ln for h in EXEMPT_HEADINGS)
        if not exempt:
            out.append((i, ln))
    return out


def _chars_no_space(s: str) -> int:
    return len(re.sub(r"\s", "", s))


def _chapter_sizes(md: str) -> dict[str, int]:
    sizes: dict[str, int] = {}
    cur = "_head"
    buf: list[str] = []
    for ln in md.splitlines():
        if ln.startswith("## "):
            sizes[cur] = _chars_no_space("\n".join(buf))
            cur, buf = ln[3:].strip(), []
        else:
            buf.append(ln)
    sizes[cur] = _chars_no_space("\n".join(buf))
    return sizes


def _pack_ids(ed: Edition) -> tuple[set[str], set[str]]:
    charts, tables = set(), set()
    cp = ed.path("data", "chart_pack.json")
    tp = ed.path("data", "table_pack.json")
    if cp.exists():
        d = json.loads(cp.read_text(encoding="utf-8"))
        items = d.get("charts", d)
        charts = {c["id"] for c in items} if isinstance(items, list) else set(items)
    if tp.exists():
        d = json.loads(tp.read_text(encoding="utf-8"))
        items = d.get("tables", d)
        tables = {t["id"] for t in items} if isinstance(items, list) else set(items)
    return charts, tables


def gate(
    ed: Edition,
    path: Path,
    kind: str,
    run_lints: bool = True,
    allow_pending: bool = False,
) -> dict:
    """kind ∈ report|explainer. 반환 {status, blocks[], warns[], stats{}}."""
    md = path.read_text(encoding="utf-8")
    lines = _body_lines(md)
    blocks: list[str] = []
    warns: list[str] = []

    pending = sorted(set(re.findall(r"<!-- PENDING:([\w\-]+) -->", md)))
    if pending and not allow_pending:
        blocks.append(
            f"발표 대기 블록 잔존 {len(pending)}건 — {pending[:5]} (release_patch 필요)"
        )

    h1 = next((ln for ln in md.splitlines() if ln.startswith("# ")), "")
    if not h1.startswith(f"# {ed.phase_tag}"):
        blocks.append(f"H1 단계 태그 누락: {h1[:60]!r} (기대 {ed.phase_tag})")

    def hits(pattern: str, literal: bool) -> list[str]:
        found = []
        for i, ln in lines:
            ok = (pattern in ln) if literal else re.search(pattern, ln)
            if ok:
                found.append(f"L{i}: {ln.strip()[:90]}")
        return found

    for w in BANNED_LITERALS:
        h = hits(w, True)
        if h:
            blocks.append(f"금지 토큰 '{w}' {len(h)}건 — {h[0]}")
    for rx in BANNED_REGEX:
        h = hits(rx, False)
        if h:
            blocks.append(f"금지 패턴 /{rx}/ {len(h)}건 — {h[0]}")
    for w in STYLE_BANNED:
        h = hits(w, True)
        if h:
            blocks.append(f"문체 금지어 '{w}' {len(h)}건 — {h[0]}")
    h = hits(RELATIVE_DATES, False)
    if h:
        blocks.append(f"상대 날짜 {len(h)}건 — {h[0]}")
    anira = len(hits(ANIRA, False))
    if anira > 5:
        warns.append(f"'A가 아니라 B' 계열 {anira}건(권고 ≤5)")

    charts, tables = _pack_ids(ed)
    bad_refs = [
        f"{t}:{i}"
        for t, i in CHART_REF.findall(md)
        if (t == "차트" and i not in charts) or (t == "표" and i not in tables)
    ]
    if bad_refs:
        blocks.append(f"존재하지 않는 차트·표 참조 {len(bad_refs)}건 — {bad_refs[:5]}")

    total = _chars_no_space(md)
    target = {"report": (50_000, 70_000), "explainer": (40_000, 50_000)}.get(kind)
    if target and not (target[0] * 0.85 <= total <= target[1] * 1.15):
        warns.append(f"분량 {total:,}자(공백 제외) — 목표 {target[0]:,}~{target[1]:,}")

    stats = {
        "chars_no_space": total,
        "chapters": _chapter_sizes(md),
        "anira": anira,
        "chart_refs": len(CHART_REF.findall(md)),
    }
    if run_lints:
        from datetime import date

        from indepth_analysis.numeric_audit import (
            build_default_sources,
            scan_numeric_issues,
        )
        from indepth_analysis.temporal_lint import scan_temporal_issues

        tf = scan_temporal_issues(md, int(ed.as_of[:4]))
        t_high = [f for f in tf if f.severity == "high"]
        stats["lint_temporal"] = [
            f"L{f.line_no} {f.severity} {f.text.strip()[:80]}"
            for f in tf
            if f.severity != "low"
        ]
        if t_high:
            blocks.append(
                f"lint-temporal HIGH {len(t_high)}건 — L{t_high[0].line_no}: "
                f"{t_high[0].text.strip()[:70]}"
            )
        try:
            nf = scan_numeric_issues(
                md,
                as_of=date.fromisoformat(ed.as_of),
                sources=build_default_sources(
                    db_path=PROJECT / "data/macro_calendar.db"
                ),
            )
        except Exception as e:  # 참조 DB 부재 등 — 자문 단계라 무시
            nf, stats["lint_numeric_error"] = [], str(e)
        n_high = [f for f in nf if f.severity == "high"]
        stats["lint_numeric"] = [
            f"L{f.line_no} {f.indicator} 인용 {f.cited} 참조 {f.reference}: {f.note[:60]}"
            for f in n_high
        ]
        if n_high:
            warns.append(f"lint-numeric HIGH {len(n_high)}건(자문 — 오탐 가능)")
    return {
        "file": str(path),
        "kind": kind,
        "status": "FAIL" if blocks else ("WARN" if warns else "PASS"),
        "blocks": blocks,
        "warns": warns,
        "stats": {**stats, "pending": pending},
    }


def _write_gate_report(ed: Edition, results: list[dict]) -> Path:
    out = ed.path("_work", f"gates_{ed.phase}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 게이트 결과 — {ed.month} {ed.phase}\n"]
    for r in results:
        md.append(f"## {Path(r['file']).name} — {r['status']}")
        md += [f"- BLOCK {b}" for b in r["blocks"]]
        md += [f"- WARN {w}" for w in r["warns"]]
        md.append(f"- 분량 {r['stats']['chars_no_space']:,}자(공백 제외)\n")
    out.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    return out


# --- 허브 v3 ---------------------------------------------------------------
def _section(md: str, prefix: str) -> str:
    out, on = [], False
    for ln in md.splitlines():
        if ln.startswith("## "):
            if on:
                break
            on = ln[3:].strip().startswith(prefix)
            continue
        if on:
            out.append(ln)
    return "\n".join(out).strip()


def build_hub(ed: Edition) -> Path:
    root = (PROJECT / ed.root).resolve()
    report = root / ed.doc_name("report")
    explainer = root / ed.doc_name("explainer")
    rep_md = report.read_text(encoding="utf-8")
    summary = _section(rep_md, "요약") or _section(rep_md, "핵심")
    session = {}
    sp = root / "session.json"
    if sp.exists():
        session = json.loads(sp.read_text(encoding="utf-8"))
    lines = [
        f"# {ed.phase_tag} 유럽 매크로 월간 리포트 {ed.month_label}호 {PHASE_KO[ed.phase]} ({ed.report_date})",
        "",
        f"- 대상 기간 {ed.window['from']} ~ {ed.window['to']} · 데이터 기준일 {ed.as_of} · 보고일 {ed.report_date}",
        f"- 입력: Bloomberg Intelligence {ed.collection} {len(session.get('documents', []))}건, 1차 통계(Eurostat·ECB), 시장 데이터, 웹 리서치",
        "",
        "## 핵심 판단",
        "",
        summary or "(리포트 요약 절 없음)",
        "",
        "## 문서",
        "",
        f"- [풀 리포트]({report})",
        f"- [해설본]({explainer})",
    ]
    prior = [
        p
        for p in PHASES[: PHASES.index(ed.phase)]
        if (root / f"_work/gates_{p}.json").exists()
    ]
    for p in prior:
        for f in sorted(root.glob(f"*_europe_macro_{p}_report.md")):
            lines.append(f"- [이전 보고: {PHASE_KO[p]} 리포트]({f})")
    lines += ["", "## BI 자료 (그룹별 정리)", ""]
    for g in session.get("groups_covered", []):
        sec = root / g["section"]
        if sec.exists():
            lines.append(f"- [{g['group']} — {g['n_docs']}건]({sec})")
    lines += [
        "",
        "## 데이터 (PowerPoint 차트·표 입력)",
        "",
        f"- 차트 팩: {root / 'data/chart_pack.json'} (차트별 CSV: {root / 'data/charts'})",
        f"- 표 팩: {root / 'data/table_pack.json'}",
        f"- 지표 사실표: {root / 'data/facts.md'}",
    ]
    ed_file = root / "_editorial" / f"{ed.phase}_editorial.md"
    if ed_file.exists():
        lines += ["", "## 편집 기록", "", f"- [방법·출처·남은 공백]({ed_file})"]
    dest = root / ed.doc_name("index")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def _update_session(ed: Edition, hub: Path) -> None:
    sp = ed.path("session.json")
    s = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    phases = s.setdefault("phases", {})
    phases[ed.phase] = {
        "report": ed.doc_name("report"),
        "explainer": ed.doc_name("explainer"),
        "index": hub.name,
        "report_date": ed.report_date,
        "as_of": ed.as_of,
        "finalized_at": datetime.now().isoformat(timespec="seconds"),
    }
    s["phase"] = ed.phase
    s.setdefault("data", {}).update(
        {
            "chart_pack": f"data/chart_pack_{ed.phase}.json",
            "table_pack": f"data/table_pack_{ed.phase}.json",
        }
    )
    sp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def register(paths: list[Path]) -> None:
    for p in paths:
        subprocess.run(
            ["uv", "run", "briefing", "register", str(p.resolve())],
            cwd=Path.home() / "projects" / "orchestrator",
            check=False,
        )


def promote(
    ed: Edition, report_rev: str, explainer_rev: str, do_register: bool, force: bool
) -> int:
    drafts = ed.path("drafts")
    pairs = [
        (drafts / f"{report_rev}.md", ed.path(ed.doc_name("report")), "report"),
        (
            drafts / f"{explainer_rev}.md",
            ed.path(ed.doc_name("explainer")),
            "explainer",
        ),
    ]
    results = [gate(ed, src, kind) for src, _, kind in pairs]
    rep = _write_gate_report(ed, results)
    for r in results:
        print(f"{Path(r['file']).name}: {r['status']}")
        for b in r["blocks"]:
            print(f"  BLOCK {b}")
        for w in r["warns"]:
            print(f"  WARN  {w}")
    if any(r["status"] == "FAIL" for r in results) and not force:
        print(f"게이트 FAIL — {rep.with_suffix('.md')}")
        return 2
    for src, dst, _ in pairs:
        shutil.copyfile(src, dst)
        shutil.copyfile(src, drafts / f"{ed.phase}_{dst.stem.split('_')[-1]}_final.md")
    for name in ("chart_pack", "table_pack", "facts"):
        f = ed.path("data", f"{name}.json")
        if f.exists():
            shutil.copyfile(f, ed.path("data", f"{name}_{ed.phase}.json"))
    numbers = ed.path("data", "NUMBERS.md")
    if numbers.exists():  # 다음 단계 Quant의 기준(NUMBERS_<base>.md)
        shutil.copyfile(numbers, ed.path("data", f"NUMBERS_{ed.phase}.md"))
    hub = build_hub(ed)
    _update_session(ed, hub)
    print(hub)
    if do_register:
        register([hub, *(dst for _, dst, _ in pairs)])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate")
    g.add_argument("--root", required=True)
    g.add_argument("--file", required=True)
    g.add_argument("--kind", default="report", choices=["report", "explainer"])
    g.add_argument("--no-lint", action="store_true")
    g.add_argument(
        "--allow-pending", action="store_true", help="초안 단계 — 발표 대기 블록 허용"
    )
    p = sub.add_parser("promote")
    p.add_argument("--root", required=True)
    p.add_argument(
        "--report", required=True, help="drafts 파일 stem (예 preview_report_r3)"
    )
    p.add_argument("--explainer", required=True)
    p.add_argument("--register", action="store_true")
    p.add_argument(
        "--force", action="store_true", help="게이트 FAIL이어도 확정(사유 기록 필수)"
    )
    h = sub.add_parser("hub")
    h.add_argument("--root", required=True)
    a = ap.parse_args()
    ed = load_edition(a.root)
    if a.cmd == "gate":
        f = Path(a.file)
        f = f if f.is_absolute() or f.exists() else ed.path(a.file)
        r = gate(ed, f, a.kind, run_lints=not a.no_lint, allow_pending=a.allow_pending)
        print(
            json.dumps(
                {k: v for k, v in r.items() if k != "stats"},
                ensure_ascii=False,
                indent=1,
            )
        )
        print(
            json.dumps(
                {k: v for k, v in r["stats"].items() if not k.startswith("lint")},
                ensure_ascii=False,
                indent=1,
            )
        )
        return 2 if r["status"] == "FAIL" else 0
    if a.cmd == "promote":
        return promote(ed, a.report, a.explainer, a.register, a.force)
    print(build_hub(ed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
