"""Mendeley WEEKLY 폴더에서 특정 날짜(YYYYMMDD) 접두 문서를 내려받고 텍스트를 추출한다.

주간 브리프 진위판단·해설 파이프라인의 1단계(결정론).

    uv run python scripts/weekly_review_fetch.py 20260907
    uv run python scripts/weekly_review_fetch.py            # 오늘 날짜(KST) 기준

산출: references/mendeley_weekly/{title}.pdf 및 동명 .md (페이지 구분 텍스트)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

import requests
from indepth_analysis.data import mendeley_client as m

DEST = Path("references/mendeley_weekly")


def list_folder_doc_ids(folder_id: str) -> list[str]:
    """폴더 문서 ID 전량(페이지네이션 — 기본 list_documents는 limit 50에서 끊김)."""
    url = f"{m.API_BASE}/folders/{folder_id}/documents"
    params: dict | None = {"limit": 500}
    ids: list[str] = []
    while url:
        r = requests.get(url, headers=m._headers(), params=params, timeout=60)
        r.raise_for_status()
        ids += [d["id"] for d in r.json()]
        url = r.links.get("next", {}).get("url")
        params = None
    return ids


def extract_md(pdf: Path) -> Path:
    doc = fitz.open(pdf)
    parts = [f"# {pdf.stem}\n\n(pages={len(doc)})\n"]
    for i, page in enumerate(doc, 1):
        parts.append(f"\n---\n## p.{i}\n\n{page.get_text('text')}")
    md = pdf.with_suffix(".md")
    md.write_text("".join(parts), encoding="utf-8")
    return md


def main() -> int:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    folder_id = m.find_folder_by_name("WEEKLY")
    if not folder_id:
        print("WEEKLY 폴더 없음", file=sys.stderr)
        return 1
    hits = []
    for did in list_folder_doc_ids(folder_id):
        r = requests.get(
            f"{m.API_BASE}/documents/{did}",
            headers={
                **m._headers(),
                "Accept": "application/vnd.mendeley-document.1+json",
            },
            timeout=60,
        )
        r.raise_for_status()
        d = r.json()
        title = d.get("title") or ""
        if title.startswith(date):
            hits.append((title, did))
    if not hits:
        print(f"{date} 접두 문서 없음", file=sys.stderr)
        return 2
    DEST.mkdir(parents=True, exist_ok=True)
    for title, did in sorted(hits):
        for f in m.list_files(did):
            fname = f.get("file_name") or f"{title}.pdf"
            pdf = m.download_file(f["id"], DEST, filename=fname)
            md = extract_md(pdf)
            print(f"{title}\t{pdf}\t{md}\t{md.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
