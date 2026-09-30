# ruff: noqa: E501
"""보조 맥락 파일(결정론) — R&I 주간 덱 유럽 섹션(D0)·KCIF 유럽 관련 보고서(K0).

    uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.context --root ROOT

- ``research/D0_weekly_europe.md``: ``references.db weekly_europe_sections``에서 대상 기간
  (window.from − 7일 ~ as_of)의 유럽 장표·타임라인 전문. 과거 보고 장표의 서사 연속성·형식 참고.
- ``research/K0_kcif_europe.md``: ``references/KCIF_md/``에서 같은 기간 발행분 중 유럽 관련
  보고서. 제목이 유럽 전용이면 본문 앞부분 6,000자, 그 외(일일 속보 등)는 유럽 언급 문단만.
LLM 호출 없음. 재실행 시 덮어쓴다.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from indepth_analysis.skills.euro_macro.monthly_brief.edition import load_edition

PROJECT = Path(__file__).resolve().parents[5]
DB = PROJECT / "references" / "references.db"
KCIF_DIR = PROJECT / "references" / "KCIF_md"
EU_TITLE = re.compile(r"ECB|유로|유럽|독일|프랑스|이탈리아|스페인|영국|BOE|EU|라가르드")
EU_TEXT = re.compile(
    r"ECB|유로존|유로화|유럽|독일|프랑스|이탈리아|스페인|영국|BOE|라가르드|Bund|분트"
)
FULL_CHARS = 6000
PARA_MAX = 3


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def weekly_sections(start: str, end: str) -> str:
    if not DB.exists():
        return "(references.db 없음)\n"
    con = sqlite3.connect(DB)
    rows = con.execute(
        "select deck_date, deck_title, page, kind, text from weekly_europe_sections "
        "where deck_date between ? and ? order by deck_date, page",
        (start, end),
    ).fetchall()
    con.close()
    out = [
        f"# R&I 주간 덱 유럽 섹션 ({start} ~ {end})\n",
        "- 사내 주간 보고 장표의 유럽 페이지 원문. 직전 보고 판단·서사 연속성 참고용",
        f"- {len(rows)}개 페이지\n",
    ]
    for d, title, page, kind, text in rows:
        out.append(f"## {d} {title} p.{page} ({kind})\n\n{text.strip()}\n")
    return "\n".join(out)


def _strip_front(md: str) -> str:
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end > 0:
            return md[end + 4 :]
    return md


def kcif_europe(start: str, end: str) -> str:
    files = sorted(KCIF_DIR.glob("*.md")) if KCIF_DIR.exists() else []
    out = [f"# KCIF 유럽 관련 보고서 ({start} ~ {end})\n"]
    n_full = n_para = 0
    for f in files:
        name = _nfc(f.stem)
        d = name[:10]
        if not (start <= d <= end):
            continue
        title = name[11:].split("_", 1)[-1].replace("_", " ")
        body = _strip_front(_nfc(f.read_text(encoding="utf-8", errors="replace")))
        body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
        if EU_TITLE.search(title):
            n_full += 1
            out.append(
                f"## {d} {title}\n\n- 원문: {f}\n\n{body.strip()[:FULL_CHARS]}\n"
            )
            continue
        paras = [
            p.strip()
            for p in re.split(r"\n\s*\n", body)
            if EU_TEXT.search(p) and len(p.strip()) > 40
        ][:PARA_MAX]
        if paras:
            n_para += 1
            joined = "\n\n".join(p[:400] for p in paras)
            out.append(f"## {d} {title} (유럽 언급 발췌)\n\n- 원문: {f}\n\n{joined}\n")
    out.insert(
        1, f"- 유럽 전용 {n_full}건(본문 앞부분) · 기타 {n_para}건(유럽 언급 문단)\n"
    )
    return "\n".join(out)


def build(root: str) -> list[Path]:
    ed = load_edition(root)
    abs_root = (PROJECT / ed.root).resolve()
    start = (date.fromisoformat(ed.window["from"]) - timedelta(days=7)).isoformat()
    end = ed.as_of
    rdir = abs_root / "research"
    rdir.mkdir(parents=True, exist_ok=True)
    d0 = rdir / "D0_weekly_europe.md"
    k0 = rdir / "K0_kcif_europe.md"
    d0.write_text(weekly_sections(start, end), encoding="utf-8")
    k0.write_text(kcif_europe(start, end), encoding="utf-8")
    return [d0, k0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    a = ap.parse_args()
    for p in build(a.root):
        print(p, p.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
