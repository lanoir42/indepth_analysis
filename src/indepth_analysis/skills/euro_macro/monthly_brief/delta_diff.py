# ruff: noqa: E501
"""단계 간 결정론 차이 추출 — 델타 리포트 집필의 입력 자료.

    M=indepth_analysis.skills.euro_macro.monthly_brief.delta_diff
    uv run python -m $M --root reports/euro_macro/monthly_brief/2026-08 \
        --base preview --phase spot [--cur-suffix rS]

비교 대상(문서 3종 + 데이터 2종):
- drafts/{base}_{report,slide,explainer}_final.md  vs  drafts/{phase}_{doc}_{cur_suffix}.md
  (cur_suffix 기본 'final'; 워크플로 진행 중에는 'rS' 등 회차 이름 지정)
- data/datapack.json: 레코드 추가·값 변경·origin 단계 표시
- data/slide_data.json: 차트별 마지막 포인트·길이 변화

산출 ``_work/delta_diff_{phase}.md`` — 절(## 제목) 단위 추가/삭제/변경 목록과 변경 절의
unified diff(문장 단위), 수치 레코드 증감, 장표 불릿 변화. LLM 호출 없음.
Delta Writer(roles/delta_report.md)는 이 파일을 근거로만 "무엇이 바뀌었나"를 서술한다.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

DOCS = ("report", "slide", "explainer")
_SENT = re.compile(r"(?<=[.다요음함임됨\)])\s+(?=[가-힣A-Za-z(\[])")


def _sections(md: str) -> dict[str, str]:
    """`## ` 절 제목 → 본문. 첫 절 이전은 '(머리)'."""
    out: dict[str, str] = {}
    key = "(머리)"
    buf: list[str] = []
    for ln in md.splitlines():
        if ln.startswith("## "):
            out[key] = "\n".join(buf).strip()
            key, buf = ln[3:].strip(), []
        else:
            buf.append(ln)
    out[key] = "\n".join(buf).strip()
    return out


def _norm_key(title: str) -> str:
    """회차·날짜 표기만 다른 절을 같은 절로 묶는다 (`변경 이력(r6)` ≈ `변경 이력(spot)`, 기간 표기)."""
    t = re.sub(r"\(.*?\)", "", title)
    t = re.sub(r"\d{4}-\d{2}-\d{2}", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _sentences(text: str) -> list[str]:
    lines: list[str] = []
    for ln in text.splitlines():
        ln = ln.rstrip()
        if not ln:
            continue
        if ln.startswith(("|", "-", "*", "#", ">")):
            lines.append(ln)
        else:
            lines.extend(s.strip() for s in _SENT.split(ln) if s.strip())
    return lines


def diff_doc(base_md: str, cur_md: str) -> tuple[list[str], dict]:
    b, c = _sections(base_md), _sections(cur_md)
    bk = {_norm_key(k): k for k in b}
    ck = {_norm_key(k): k for k in c}
    added = [ck[k] for k in ck if k not in bk]
    removed = [bk[k] for k in bk if k not in ck]
    changed: list[tuple[str, str, list[str]]] = []
    same: list[str] = []
    for nk, ctitle in ck.items():
        if nk not in bk:
            continue
        bt = b[bk[nk]]
        ct = c[ctitle]
        if bt == ct:
            same.append(ctitle)
            continue
        ud = list(
            difflib.unified_diff(
                _sentences(bt),
                _sentences(ct),
                lineterm="",
                n=0,
                fromfile=f"base: {bk[nk]}",
                tofile=f"cur: {ctitle}",
            )
        )
        changed.append((bk[nk], ctitle, ud))
    lines: list[str] = []
    lines.append(
        f"- 절 수: base {len(b)} → cur {len(c)} · 추가 {len(added)} · 삭제 {len(removed)} · 변경 {len(changed)} · 동일 {len(same)}"
    )
    lines.append(
        f"- 글자 수: base {len(base_md):,} → cur {len(cur_md):,} ({len(cur_md) - len(base_md):+,})"
    )
    if added:
        lines.append("- 추가된 절: " + " · ".join(f"`{t}`" for t in added))
    if removed:
        lines.append("- 삭제된 절: " + " · ".join(f"`{t}`" for t in removed))
    if same:
        lines.append("- 동일 절(문자 단위 일치): " + " · ".join(f"`{t}`" for t in same))
    for bt, ct, ud in changed:
        head = f"`{ct}`" if bt == ct else f"`{bt}` → `{ct}`"
        plus = sum(1 for ln in ud if ln.startswith("+") and not ln.startswith("+++"))
        minus = sum(1 for ln in ud if ln.startswith("-") and not ln.startswith("---"))
        lines.append("")
        lines.append(f"### 변경 절 {head} (−{minus} / +{plus} 문장)")
        lines.append("```diff")
        lines.extend(ud[2:] if len(ud) > 2 else ud)
        lines.append("```")
    for t in added:
        lines.append("")
        lines.append(f"### 추가 절 `{t}` 전문")
        lines.append(c[t])
    stats = {
        "added": added,
        "removed": removed,
        "changed": [ct for _, ct, _ in changed],
        "same": same,
        "chars_base": len(base_md),
        "chars_cur": len(cur_md),
    }
    return lines, stats


def _rec_key(r: dict) -> str:
    return str(
        r.get("id")
        or r.get("key")
        or f"{r.get('indicator')}|{r.get('period')}|{r.get('source')}"
    )


def diff_datapack(base: dict | list, cur: dict | list) -> list[str]:
    def recs(x):
        if isinstance(x, dict):
            for k in ("records", "data", "items"):
                if isinstance(x.get(k), list):
                    return x[k]
            return []
        return x if isinstance(x, list) else []

    br = {_rec_key(r): r for r in recs(base) if isinstance(r, dict)}
    cr = {_rec_key(r): r for r in recs(cur) if isinstance(r, dict)}
    added = [k for k in cr if k not in br]
    removed = [k for k in br if k not in cr]
    changed = [k for k in cr if k in br and cr[k] != br[k]]
    out = [
        f"- 레코드: base {len(br)} → cur {len(cr)} · 추가 {len(added)} · 삭제 {len(removed)} · 값 변경 {len(changed)}"
    ]
    for k in added[:80]:
        r = cr[k]
        out.append(
            f"  - + `{k}` = {r.get('value')} {r.get('unit', '')} ({r.get('origin') or r.get('source', '')}; {r.get('label', '')})".rstrip()
        )
    if len(added) > 80:
        out.append(f"  - … 외 {len(added) - 80}건")
    for k in changed[:40]:
        out.append(
            f"  - ~ `{k}`: {br[k].get('value')} → {cr[k].get('value')}  ⚠ 기존 레코드 값 변경(규약 위반 가능 — conflict 기록 확인)"
        )
    for k in removed[:40]:
        out.append(f"  - − `{k}` 삭제  ⚠ 정본 삭제는 규약 위반 가능")
    return out


def diff_slide_data(base: dict, cur: dict) -> list[str]:
    bc = base.get("charts", {}) if isinstance(base, dict) else {}
    cc = cur.get("charts", {}) if isinstance(cur, dict) else {}
    out = [f"- 차트: base {len(bc)} → cur {len(cc)}"]
    for k in cc:
        if k not in bc:
            out.append(f"  - + 차트 `{k}` 신규")
            continue
        if bc[k] == cc[k]:
            continue

        def last(ch):
            s = ch.get("series") or ch.get("data") or {}
            if isinstance(s, dict):
                return {
                    n: (v[-1] if isinstance(v, list) and v else v)
                    for n, v in list(s.items())[:6]
                }
            if isinstance(s, list):
                return [
                    (x.get("name"), (x.get("data") or [None])[-1])
                    for x in s[:6]
                    if isinstance(x, dict)
                ]
            return None

        out.append(
            f"  - ~ 차트 `{k}` 변경: 마지막 포인트 {last(bc[k])} → {last(cc[k])}; x축 {len(bc[k].get('x_labels', []))} → {len(cc[k].get('x_labels', []))}"
        )
    for k in bc:
        if k not in cc:
            out.append(f"  - − 차트 `{k}` 제거")
    return out


def build(root: Path, base: str, phase: str, cur_suffix: str) -> Path:
    drafts = root / "drafts"
    data = root / "data"
    work = root / "_work"
    work.mkdir(exist_ok=True)
    lines = [
        f"# 단계 간 결정론 차이: {base} → {phase} (cur={cur_suffix})",
        "",
        "> `delta_diff.py` 산출. LLM 미개입. 절 단위 비교(회차·날짜 괄호 표기는 같은 절로 취급), 변경 절은 문장 단위 unified diff.",
        "> Delta Writer는 이 파일에 없는 변경을 '바뀌었다'고 쓰지 않는다.",
        "",
    ]
    summary: dict = {}
    for d in DOCS:
        bp = drafts / f"{base}_{d}_final.md"
        cp = drafts / f"{phase}_{d}_{cur_suffix}.md"
        lines.append(f"## 문서: {d}")
        lines.append(f"- base `{bp}` · cur `{cp}`")
        if not bp.exists() or not cp.exists():
            lines.append(
                f"- ⚠ 파일 없음: {'base ' if not bp.exists() else ''}{'cur' if not cp.exists() else ''}"
            )
            lines.append("")
            continue
        dl, st = diff_doc(bp.read_text("utf-8"), cp.read_text("utf-8"))
        summary[d] = st
        lines.extend(dl)
        lines.append("")
    lines.append("## 데이터: datapack.json")
    dp_base = data / f"datapack_{base}.json"
    dp_cur = data / "datapack.json"
    if dp_base.exists() and dp_cur.exists():
        lines.append(f"- base 스냅샷 `{dp_base}` · cur `{dp_cur}`")
        lines.extend(
            diff_datapack(
                json.loads(dp_base.read_text("utf-8")),
                json.loads(dp_cur.read_text("utf-8")),
            )
        )
    else:
        lines.append(
            f"- ⚠ 이전 단계 스냅샷 `{dp_base.name}` 없음 — finalize_phase.sh가 단계 마감 시 `datapack_{{phase}}.json`·`slide_data_{{phase}}.json` 스냅샷을 남긴다. 이번 비교는 origin 필드로 대체:"
        )
        if dp_cur.exists():
            j = json.loads(dp_cur.read_text("utf-8"))
            recs = j.get("records", j) if isinstance(j, dict) else j
            tag = [
                r
                for r in recs
                if isinstance(r, dict)
                and phase in str(r.get("origin", "")) + str(r.get("source_file", ""))
            ]
            lines.append(f"  - origin/source_file에 `{phase}` 포함 레코드 {len(tag)}건")
            for r in tag[:80]:
                lines.append(
                    f"    - `{_rec_key(r)}` = {r.get('value')} {r.get('unit', '')} ({r.get('label', '')})".rstrip()
                )
    lines.append("")
    lines.append("## 데이터: slide_data.json")
    sd_base = data / f"slide_data_{base}.json"
    sd_cur = data / "slide_data.json"
    if sd_base.exists() and sd_cur.exists():
        lines.extend(
            diff_slide_data(
                json.loads(sd_base.read_text("utf-8")),
                json.loads(sd_cur.read_text("utf-8")),
            )
        )
    else:
        lines.append(f"- ⚠ 이전 단계 스냅샷 `{sd_base.name}` 없음 (위와 동일 사유)")
    lines.append("")
    lines.append("## 요약(JSON)")
    lines.append("```json")
    lines.append(json.dumps(summary, ensure_ascii=False, indent=1))
    lines.append("```")
    dest = work / f"delta_diff_{phase}.md"
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--base", required=True, help="이전 단계 (preview|spot)")
    ap.add_argument("--phase", required=True, help="현재 단계 (spot|review)")
    ap.add_argument(
        "--cur-suffix", default="final", help="현재 단계 드래프트 접미 (final|rS|r3 …)"
    )
    a = ap.parse_args()
    print(build(Path(a.root), a.base, a.phase, a.cur_suffix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
