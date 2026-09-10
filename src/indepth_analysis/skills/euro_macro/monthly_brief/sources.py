"""Mendeley 소스 수집·텍스트화·유럽 섹션 인덱싱 (결정론 단계).

    M=indepth_analysis.skills.euro_macro.monthly_brief.sources
    uv run python -m $M europe 202608
    uv run python -m $M weekly
    uv run python -m $M index-weekly

- `europe YYYYMM` : 폴더 `EUROPE YYYYMM` 전량
                     → references/mendeley_europe/YYYYMM/{pdf,md}
- `weekly`         : WEEKLY 폴더의 `*_거시경제_동향*` 전량 → references/mendeley_weekly/
- `index-weekly`   : 주간 덱 .md에서 유럽 관련 페이지를 추출해 references.db
                     `weekly_europe_sections`(+FTS)에 적재
기존 파일은 건너뛴다(멱등).
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import fitz  # PyMuPDF

import requests
from indepth_analysis.data import mendeley_client as m

REF_ROOT = Path("references")
WEEKLY_DIR = REF_ROOT / "mendeley_weekly"
EUROPE_DIR = REF_ROOT / "mendeley_europe"
DB_PATH = REF_ROOT / "references.db"

_EUROPE_PAGE_RE = re.compile(
    r"Macroeconomic Brief:\s*(유럽|Europe|EU)|Macroeconomy Brief:\s*(유럽|Europe)"
    r"|Market Brief:\s*(유럽|Europe)",
    re.IGNORECASE,
)
_EUROPE_KW = (
    "ECB",
    "유로존",
    "유로화",
    "EUR/USD",
    "라가르드",
    "HICP",
    "독일",
    "프랑스",
    "유럽",
    "Eurostat",
    "Bund",
    "BTP",
    "OAT",
)


def _doc_ids(folder_id: str) -> list[str]:
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


def _doc_meta(doc_id: str) -> dict:
    r = requests.get(
        f"{m.API_BASE}/documents/{doc_id}",
        headers={**m._headers(), "Accept": "application/vnd.mendeley-document.1+json"},
        params={"view": "all"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _folder_id(name: str) -> str:
    fid = m.find_folder_by_name(name)
    if fid:
        return fid
    r = requests.get(
        f"{m.API_BASE}/folders", headers=m._headers(), params={"limit": 200}, timeout=60
    )
    r.raise_for_status()
    for fo in r.json():
        if fo.get("name") == name:
            return fo["id"]
    raise SystemExit(f"Mendeley 폴더 없음: {name}")


def extract_md(pdf: Path, title: str | None = None) -> Path:
    md = pdf.with_suffix(".md")
    if md.exists() and md.stat().st_size > 0:
        return md
    doc = fitz.open(pdf)
    parts = [f"# {title or pdf.stem}\n\n(pages={len(doc)}; file={pdf.name})\n"]
    for i, page in enumerate(doc, 1):
        parts.append(f"\n---\n## p.{i}\n\n{page.get_text('text')}")
    md.write_text("".join(parts), encoding="utf-8")
    return md


def _safe(name: str) -> str:
    return re.sub(r"[^\w\-. ]+", "_", name).strip()[:120]


def fetch_folder(
    folder_name: str, dest: Path, title_filter=None
) -> list[tuple[str, Path, Path]]:
    """폴더 문서 전량 다운로드 + 텍스트화. 반환 [(title, pdf, md)]."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for did in _doc_ids(_folder_id(folder_name)):
        d = _doc_meta(did)
        title = (d.get("title") or did).strip()
        if title_filter and not title_filter(title):
            continue
        for f in m.list_files(did):
            fname = f.get("file_name") or f"{_safe(title)}.pdf"
            pdf = dest / fname
            if not pdf.exists():
                pdf = m.download_file(f["id"], dest, filename=fname)
            md = extract_md(pdf, title=title)
            out.append((title, pdf, md))
            print(f"{title}\t{md}\t{md.stat().st_size}")
    return out


# ---------------------------------------------------------------------------
# 주간 덱 유럽 섹션 인덱스
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS weekly_europe_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deck_date TEXT NOT NULL,          -- YYYY-MM-DD (덱 제목 접두)
    deck_title TEXT NOT NULL,
    page INTEGER NOT NULL,
    kind TEXT NOT NULL,               -- brief_europe | timeline_europe | mention
    text TEXT NOT NULL,
    md_path TEXT NOT NULL,
    UNIQUE(deck_title, page)
);
CREATE VIRTUAL TABLE IF NOT EXISTS weekly_europe_fts USING fts5(
    text, deck_title UNINDEXED, deck_date UNINDEXED, page UNINDEXED,
    content='weekly_europe_sections', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS wes_ai AFTER INSERT ON weekly_europe_sections BEGIN
  INSERT INTO weekly_europe_fts(rowid, text, deck_title, deck_date, page)
  VALUES (new.id, new.text, new.deck_title, new.deck_date, new.page);
END;
CREATE TRIGGER IF NOT EXISTS wes_ad AFTER DELETE ON weekly_europe_sections BEGIN
  INSERT INTO weekly_europe_fts(weekly_europe_fts, rowid, text, deck_title,
                                deck_date, page)
  VALUES ('delete', old.id, old.text, old.deck_title, old.deck_date, old.page);
END;
"""


def _deck_date(stem: str) -> str | None:
    mo = re.match(r"(\d{8})", stem)
    if mo:
        s = mo.group(1)
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    mo = re.match(r"(\d{6})_", stem)
    if mo:
        s = mo.group(1)
        return f"20{s[:2]}-{s[2:4]}-{s[4:]}"
    return None


def index_weekly_europe(md_dir: Path = WEEKLY_DIR, db_path: Path = DB_PATH) -> int:
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    n = 0
    for md in sorted(md_dir.glob("*.md")):
        if "자산시장" in md.name:
            continue
        date = _deck_date(md.stem)
        if not date:
            continue
        pages = re.split(r"\n---\n## p\.(\d+)\n", md.read_text(encoding="utf-8"))
        # pages = [head, num1, text1, num2, text2, ...]
        for i in range(1, len(pages) - 1, 2):
            pno, text = int(pages[i]), pages[i + 1]
            if _EUROPE_PAGE_RE.search(text):
                kind = "brief_europe"
            elif "Europe + MENA" in text or "Europe" in text[:400]:
                kind = "timeline_europe"
            elif sum(text.count(k) for k in _EUROPE_KW) >= 3:
                kind = "mention"
            else:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO weekly_europe_sections"
                "(deck_date, deck_title, page, kind, text, md_path) "
                "VALUES (?,?,?,?,?,?)",
                (date, md.stem, pno, kind, text.strip(), str(md)),
            )
            n += cur.rowcount
    conn.commit()
    conn.close()
    return n


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "europe":
        yyyymm = argv[1]
        fetch_folder(f"EUROPE {yyyymm}", EUROPE_DIR / yyyymm)
    elif cmd == "weekly":
        fetch_folder("WEEKLY", WEEKLY_DIR, title_filter=lambda t: "거시경제_동향" in t)
    elif cmd == "index-weekly":
        n = index_weekly_europe()
        print(f"weekly_europe_sections +{n} rows")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
