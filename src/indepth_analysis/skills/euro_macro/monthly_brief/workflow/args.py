"""Workflow(`noir_v3.js`) 인자 생성 — edition.json·coverage.yaml·session.json에서.

    uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.workflow.args \
        --root reports/euro_macro/monthly_brief/2026-09 [--write]

출력 JSON을 Claude Code의 Workflow 도구에
``{scriptPath: <PKG>/workflow/noir_v3.js, args: <이 JSON>}``으로 넘긴다.
``--write``는 ``ROOT/_work/workflow_args_<phase>.json``에도 저장한다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from indepth_analysis.skills.euro_macro.monthly_brief.edition import load_edition

PKG = Path(__file__).resolve().parent.parent
PROJECT = PKG.parents[4]
POLISH_WRITTEN = {"summary", "appendix"}


def build(root: str, max_rounds: int = 2) -> dict:
    ed = load_edition(root)
    abs_root = (PROJECT / ed.root).resolve()
    cov = yaml.safe_load((PKG / "coverage.yaml").read_text(encoding="utf-8"))
    effort_high = set(cov.get("effort_policy", {}).get("high", []))
    explainers = {
        e["maps_to"]: e
        for e in cov["explainer"]["chapters"]
        if e.get("maps_to") and ed.phase in e.get("phases", [ed.phase])
    }
    base = ed.base_phase
    chapters = []
    for c in cov["report"]["chapters"]:
        if c["key"] in POLISH_WRITTEN:
            continue
        if ed.phase not in (c.get("phases") or [ed.phase]):
            continue
        ex = explainers.get(c["key"])
        item = {
            "key": c["key"],
            "title": c["title"],
            "target_chars": c["target_chars"],
            "effort": "high" if c["key"] in effort_high else "medium",
            "role": c.get("written_by") or "chief_chapter",
            "explainer": (
                {
                    "key": ex["key"],
                    "title": ex["title"],
                    "target_chars": ex["target_chars"],
                }
                if ex
                else None
            ),
        }
        if base:
            prev = abs_root / "drafts" / f"{base}_report_final.md"
            if prev.exists():
                item["base_draft"] = f"{prev} (해당 장 절)"
        chapters.append(item)
    groups: list[str] = []
    sp = abs_root / "session.json"
    if sp.exists():
        s = json.loads(sp.read_text(encoding="utf-8"))
        groups = [g["group"] for g in s.get("groups_covered", []) if g.get("n_docs")]
    return {
        "root": str(abs_root),
        "phase": ed.phase,
        "asOf": ed.as_of,
        "reportDate": ed.report_date,
        "pkg": str(PKG),
        "project": str(PROJECT),
        "chapters": chapters,
        "groups": groups,
        "maxRounds": max_rounds,
        "hasPending": ed.has_pending,
        "pendingWindow": ed.pending_window if ed.has_pending else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--max-rounds", type=int, default=2)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    args = build(a.root, a.max_rounds)
    text = json.dumps(args, ensure_ascii=False, indent=1)
    if a.write:
        out = Path(args["root"]) / "_work" / f"workflow_args_{args['phase']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
