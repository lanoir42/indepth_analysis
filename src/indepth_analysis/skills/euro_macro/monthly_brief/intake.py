"""v3 WP1 Intake — Mendeley EUROPE 컬렉션 결정론 스캐폴드.

    M=indepth_analysis.skills.euro_macro.monthly_brief.intake
    uv run python -m $M scaffold --month 2026-09 [--root ROOT] [--as-of D]

``references/mendeley_europe/<YYYYMM>/*.md``(``sources.fetch_folder`` 산출)를 읽어

1. 1면 헤더에서 진짜 제목·발행 시각·저자를 파싱한다(Mendeley 제목·등록일은
   차트 캡션·업로드일이라 쓰지 않는다). 두 형식:
   - ``bi_story``: ``MM/DD/YYYY HH:MM:SS [BI] Bloomberg Intelligence`` + 제목 + ``By …``
   - ``bi_web``: 웹 내보내기(저자/``Team:`` 블록 → ``Table of Contents`` →
     총서명 → ``1. 제목``), 발행일 = 본문 ``(MM/DD/YY)`` 스탬프의 최댓값
2. 배포 고지·면책·인쇄 시각을 제거한 정규화 본문의 sha256 앞 16자 = ``sha16``
3. 중복: 동일 sha16(월 간 재수록 포함) · 동일 제목+발행 시각(개정판 번호 무시)
   → ``dup_of``. 조각: 헤더 없는 캡션 수준 문서·다른 문서에 포함된 차트 페이지
4. 계열·국가·그룹 규칙 분류 → ``references.db`` ``europe_docs`` 멱등 upsert
   (+ 수록 관계 ``europe_doc_files``)
5. ``ROOT/session.json``·``ROOT/documents/doc_cards.md``·``ROOT/sections/<G>.md``

세션 문서 범위 = 당월 컬렉션 전량 + 전월 컬렉션 중 발행일이 창(window) 안인 문서.
재실행 멱등(카드가 늘면 uncarded만 줄어든다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from indepth_analysis.skills.euro_macro.monthly_brief.contract import GROUPS
from indepth_analysis.skills.euro_macro.monthly_brief.edition import (
    BASE_DIR,
    VERSION,
    Edition,
    load_edition,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
EUROPE_DIR = Path("references/mendeley_europe")
CARDS_DIR = EUROPE_DIR / "cards"
DB_PATH = Path("references/references.db")
NARRATIVE = "<!-- NARRATIVE -->"
SCAFFOLD_END = "<!-- SCAFFOLD:END -->"
STALE_GRACE_DAYS = 7
FRAGMENT_MIN_CHARS = 500
FRAGMENT_CONTAIN = 0.8
NEAR_DUP_MUTUAL = 0.9  # 모음물(웹 내보내기) 판본 간 상호 포함률

GROUP_KO = {
    "ECB": "ECB 통화정책",
    "EA_MACRO": "유로존 거시",
    "DE": "독일",
    "FR": "프랑스",
    "IT": "이탈리아",
    "ES": "스페인",
    "UK": "영국",
    "EU_POLICY": "EU 정책·정치",
    "ENERGY_EXTERNAL": "에너지·대외",
    "GLOBAL": "글로벌",
}

# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------

_MD_HEAD = re.compile(r"^# (?P<title>.*)\n+\(pages=(?P<pages>\d+); file=(?P<file>.*)\)")
_PAGE_SPLIT = re.compile(r"\n---\n## p\.(\d+)\n")
_BI_HEAD = re.compile(
    r"^(?P<m>\d{2})/(?P<d>\d{2})/(?P<y>\d{4})\s+(?P<t>\d{2}:\d{2}):\d{2}\s+\[BI\]"
)
_STAMP = re.compile(r"\((\d{2})/(\d{2})/(\d{2})\)")
_BY = re.compile(r"^By (.+)$")
_ROLE = re.compile(r"\s*\((?:Analyst|Economist|Economics|Strategist|[^)]*)\)")

_BOILER_LINE = re.compile(
    r"^(This document is being provided for the exclusive use of .*"
    r"|Bloomberg\s*®?"
    r"|Bloomberg®\s*\d{2}/\d{2}/\d{4}.*"
    r"|Printed on \d{2}/\d{2}/\d{4}"
    r"|Page \d+ of \d+"
    r"|News Story"
    r"|.*\bat NC CORPORATION\b.*)$"
)
_DISCLAIMER_START = "This report may not be modified or altered in any way"
_DISCLAIMER_END = re.compile(r"instruments by BFLP, BLP or their affiliates\.\s*$")
_CONTACT = re.compile(r"^To contact the (editor|economist|analyst)s? ")

SERIES_WORDS = {
    "PREVIEW": "PREVIEW",
    "REACT": "REACT",
    "INSIGHT": "INSIGHT",
    "WEEK AHEAD": "WEEK_AHEAD",
}
PREFIX_GEO = [
    ("EURO-AREA", "EA"),
    ("EUROAREA", "EA"),
    ("EURO AREA", "EA"),
    ("GERMANY", "DE"),
    ("FRANCE", "FR"),
    ("ITALY", "IT"),
    ("SPAIN", "ES"),
    ("UK", "UK"),
    ("EUROPE", "EU"),
    ("EU", "EU"),
    ("ECB", "ECB"),
    ("EMEA", "EU"),
    ("GLOBAL", "GLOBAL"),
    ("US", "US"),
    ("CHINA", "CN"),
]
GEO_GROUP = {
    "EA": "EA_MACRO",
    "DE": "DE",
    "FR": "FR",
    "IT": "IT",
    "ES": "ES",
    "UK": "UK",
    "EU": "EU_POLICY",
    "ECB": "ECB",
    "GLOBAL": "GLOBAL",
    "US": "GLOBAL",
    "CN": "GLOBAL",
    "OTHER": "GLOBAL",
}
# 제목·리드 키워드 → 보조 그룹 (단어 경계, 대소문자 무시)
GROUP_KW = {
    "ECB": r"\bECB\b|Lagarde|Governing Council|deposit rate|European Central Bank",
    "EA_MACRO": r"euro[- ]?area|eurozone|euro zone|\bHICP\b",
    "DE": r"\bGerman|\bGermany\b|\bMerz\b|\bAfD\b|\bIfo\b|\bBund\b|Bundesbank",
    "FR": r"\bFrance\b|\bFrench\b|\bOAT\b|Macron|Lecornu|Le Pen|Bardella",
    "IT": r"\bItal(y|ian)\b|\bBTP\b|Meloni",
    "ES": r"\bSpain\b|\bSpanish\b|S[aá]nchez",
    "UK": r"\bUK\b|\bBOE\b|Bank of England|\bgilts?\b|Britain|British|Reeves",
    "EU_POLICY": r"\bEU\b|European Commission|Brussels|\bMFF\b|China Shock"
    r"|European Union|Ukraine|\bdefen[cs]e\b|\btariffs?\b",
    "ENERGY_EXTERNAL": r"\boil\b|natural gas|\bgas\b|\benergy\b|\bIran\b|Brent|\bTTF\b"
    r"|Persian Gulf|China Shock|commodit",
}
_GROUP_RE = {g: re.compile(p, re.IGNORECASE) for g, p in GROUP_KW.items()}


@dataclass
class Doc:
    md_path: str  # 저장소 루트 기준 상대경로
    pdf_path: str
    yyyymm: str
    mendeley_title: str
    pages: int
    fmt: str  # bi_story | bi_web | unknown
    title: str
    published_at: str | None  # ISO (YYYY-MM-DDTHH:MM 또는 YYYY-MM-DD)
    author: str
    body: str  # 정리된 본문
    lead: str  # 제목 다음 첫 800자
    series: str = "OTHER"
    geo: str = "OTHER"
    groups: list[str] = field(default_factory=list)
    sha16: str = ""
    dup_of: str | None = None
    dup_reason: str = ""
    fragment: bool = False

    @property
    def collection(self) -> str:
        return f"EUROPE {self.yyyymm}"

    @property
    def chars(self) -> int:
        return len(self.body)

    @property
    def date(self) -> str | None:
        return self.published_at[:10] if self.published_at else None


def split_md(text: str) -> tuple[str, int, str, list[str]]:
    """(mendeley_title, pages, file, [page_text...])."""
    mo = _MD_HEAD.match(text)
    if not mo:
        raise ValueError("md 헤더 형식 아님")
    parts = _PAGE_SPLIT.split(text)
    pages = [parts[i + 1] for i in range(1, len(parts) - 1, 2)]
    return mo["title"].strip(), int(mo["pages"]), mo["file"].strip(), pages


def clean_lines(text: str) -> list[str]:
    """배포 고지·면책·인쇄 시각·연락처 블록을 제거한 줄 목록."""
    out: list[str] = []
    skip_disc = False
    skip_contact = 0
    for raw in text.splitlines():
        line = raw.strip()
        if skip_disc:
            if _DISCLAIMER_END.search(line):
                skip_disc = False
            continue
        if line.startswith(_DISCLAIMER_START):
            skip_disc = not _DISCLAIMER_END.search(line)
            continue
        if _CONTACT.match(line):
            skip_contact = 1
            continue
        if skip_contact and "@bloomberg.net" in line:
            continue
        skip_contact = 0
        if not line or _BOILER_LINE.match(line):
            continue
        out.append(line)
    return out


def normalize(text: str) -> str:
    t = text.lower().replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip()


def sha16_of(body: str) -> str:
    return hashlib.sha256(normalize(body).encode("utf-8")).hexdigest()[:16]


def _title_from_file(fname: str) -> str:
    stem = Path(fname).stem
    stem = stem.replace("___", " - ").replace("__", " ").replace("_", " ")
    return re.sub(r"\s+", " ", stem).strip()


def _clean_author(s: str) -> str:
    s = _ROLE.sub("", s)
    s = s.replace(" and ", ", ").replace(" & ", ", ")
    return ", ".join(x.strip() for x in s.split(",") if x.strip())


def parse_header(page1: str, fname: str = "") -> dict:
    """1면 텍스트 → {fmt,title,published_at,author,label,lead_start}."""
    lines = [ln.strip() for ln in page1.splitlines() if ln.strip()]
    res = {
        "fmt": "unknown",
        "title": "",
        "published_at": None,
        "author": "",
        "label": "",
        "lead_index": 0,
    }
    if lines:
        mo = _BI_HEAD.match(lines[0])
        if mo:
            res["fmt"] = "bi_story"
            res["published_at"] = f"{mo['y']}-{mo['m']}-{mo['d']}T{mo['t']}"
            res["title"] = lines[1] if len(lines) > 1 else ""
            i = 2
            if len(lines) > 2 and (b := _BY.match(lines[2])):
                res["author"] = _clean_author(b.group(1))
                i = 3
            res["lead_index"] = i
            return res
    if any(ln.startswith("Team:") for ln in lines[:12]):
        res["fmt"] = "bi_web"
        authors = [
            lines[k - 1]
            for k, ln in enumerate(lines[:20])
            if ln.startswith("Team:") and k > 0
        ]
        res["author"] = ", ".join(dict.fromkeys(authors))
        toc = next(
            (k for k, ln in enumerate(lines[:40]) if ln == "Table of Contents"), None
        )
        start = 0
        if toc is not None:
            res["label"] = lines[toc + 1] if toc + 1 < len(lines) else ""
            for k in range(toc + 1, min(toc + 6, len(lines))):
                mo = re.match(r"^1\.\s+(.+)$", lines[k])
                if mo:
                    res["title"] = mo.group(1)
                    start = k + 1
                    break
        if not res["title"]:
            for k, ln in enumerate(lines[:40]):
                if re.match(r"^BE Primer:", ln):
                    res["title"] = ln
                    res["label"] = next(
                        (x for x in reversed(lines[:k]) if "Primer" in x),
                        res["label"],
                    )
                    start = k + 1
                    break
        if not res["title"]:
            res["title"] = _title_from_file(fname)
        res["lead_index"] = start
        return res
    res["title"] = _title_from_file(fname) if fname else (lines[0] if lines else "")
    return res


def _max_stamp(text: str) -> str | None:
    best = None
    for m, d, y in _STAMP.findall(text):
        try:
            dt = date(2000 + int(y), int(m), int(d))
        except ValueError:
            continue
        best = dt if best is None or dt > best else best
    return best.isoformat() if best else None


def classify_series(title: str, label: str = "", fname: str = "") -> str:
    t = f"{title} {label} {fname}".upper().replace("_", " ")
    if "FAULT LINES" in t:
        return "FAULT_LINES"
    if re.search(r"ECO WRAP|ECO BEST|ECONOMIC ANALYSIS-?\s*WRAP", t):
        return "ECO_WRAP"
    if "WEEK AHEAD" in t:
        return "WEEK_AHEAD"
    if "PRIMER" in t:
        return "PRIMER"
    head = title.split(":")[0].upper() if ":" in title else title.upper()[:40]
    for word, s in SERIES_WORDS.items():
        if re.search(rf"\b{word}\b", head):
            return s
    if re.search(r"OUTLOOK|FORECAST BOOK|TRACKER|WHAT'S DRIVING|YIELDS 2026", t):
        return "OUTLOOK"
    for word, s in SERIES_WORDS.items():
        if re.search(rf"\b{word}\b", t):
            return s
    return "OTHER"


_TITLE_GEO = [
    ("DE", r"\bGerman|\bGermany"),
    ("FR", r"\bFrance|\bFrench"),
    ("IT", r"\bItal(y|ian)"),
    ("ES", r"\bSpain|\bSpanish"),
    ("UK", r"\bUK\b|\bBritain|\bBritish"),
    ("EA", r"euro[- ]?area|eurozone"),
]
_SERIES_HEAD = re.compile(r"\b(PREVIEW|REACT|INSIGHT|WEEK AHEAD)\b")


def classify_geo(title: str, label: str = "", series: str = "") -> str:
    """접두(``GERMANY REACT:`` 등) → 제목 국가 키워드 → 총서명 → GLOBAL/OTHER.

    접두 규칙은 계열어가 붙은 BI 스토리 제목에만 적용한다(``US AI Risks…:
    Eco Wrap`` 같은 모음물 제목의 첫 단어는 국가 표지가 아니다).
    """
    head = title.upper().strip()
    if _SERIES_HEAD.search(head.split(":")[0]):
        for pref, geo in PREFIX_GEO:
            if re.match(rf"^{re.escape(pref)}\b", head):
                return geo
    lab = label.upper()
    if series == "ECO_WRAP":
        return "GLOBAL"
    for geo, rx in _TITLE_GEO:
        if re.search(rx, title, re.IGNORECASE):
            return geo
    if "EURO-AREA" in lab or "EURO AREA" in lab:
        return "EA"
    return "GLOBAL" if label or "WRAP" in head or "FAULT LINES" in head else "OTHER"


def classify_groups(title: str, lead: str, geo: str) -> list[str]:
    primary = GEO_GROUP.get(geo, "GLOBAL")
    groups = [primary]
    title_hits = [g for g, rx in _GROUP_RE.items() if rx.search(title)]
    lead_hits = {g: len(rx.findall(lead)) for g, rx in _GROUP_RE.items()}
    for g in title_hits:
        if g not in groups:
            groups.append(g)
    for g, n in sorted(lead_hits.items(), key=lambda kv: -kv[1]):
        if n >= 2 and g not in groups:
            groups.append(g)
    if primary == "GLOBAL" and len(groups) > 1:
        # 글로벌 모음물은 유럽 그룹을 앞세우되 GLOBAL은 유지
        groups = [g for g in groups if g != "GLOBAL"] + ["GLOBAL"]
    return groups[:4]


def load_doc(md: Path, repo_root: Path) -> Doc:
    text = md.read_text(encoding="utf-8", errors="replace")
    mtitle, pages, fname, page_texts = split_md(text)
    raw1 = page_texts[0] if page_texts else ""
    hdr = parse_header(raw1, fname)
    body_lines: list[str] = []
    for pt in page_texts:
        body_lines.extend(clean_lines(pt))
    # 헤더 줄(발행 시각)은 본문 해시에서 제외하지 않는다 — 동일 기사 판정에 유리
    body = "\n".join(body_lines)
    pub = hdr["published_at"]
    if hdr["fmt"] != "bi_story":
        pub = _max_stamp(body)
    p1 = clean_lines(raw1)
    lead = " ".join(p1[hdr["lead_index"] :])[:800] if p1 else ""
    rel = md.resolve().relative_to(repo_root.resolve())
    pdf = rel.with_suffix(".pdf")
    d = Doc(
        md_path=str(rel),
        pdf_path=str(pdf),
        yyyymm=md.parent.name,
        mendeley_title=mtitle,
        pages=pages,
        fmt=hdr["fmt"],
        title=hdr["title"] or mtitle,
        published_at=pub,
        author=hdr["author"],
        body=body,
        lead=lead,
    )
    d.series = classify_series(d.title, hdr["label"], fname)
    d.geo = classify_geo(d.title, hdr["label"], d.series)
    d.groups = classify_groups(d.title, lead, d.geo)
    d.sha16 = sha16_of(body)
    return d


# ---------------------------------------------------------------------------
# 중복·조각
# ---------------------------------------------------------------------------


def _title_key(t: str) -> str:
    t = re.sub(r"\(\d\)\s*$", "", t.strip())
    return normalize(re.sub(r"[^\w\s]", " ", t))


def _line_set(body: str) -> set[str]:
    return {normalize(ln) for ln in body.splitlines() if len(ln) >= 30}


def mark_dups_and_fragments(docs: list[Doc]) -> None:
    """docs는 수집 순서(전월→당월) 그대로. 원본 = 먼저 등장한 문서."""
    order = {id(d): i for i, d in enumerate(docs)}
    ordered = sorted(
        docs, key=lambda d: (d.yyyymm, d.published_at or "9999", order[id(d)])
    )
    seen_sha: dict[str, Doc] = {}
    seen_key: dict[tuple[str, str], Doc] = {}
    for d in ordered:
        if d.sha16 in seen_sha:
            orig = seen_sha[d.sha16]
            if orig.yyyymm == d.yyyymm:
                d.dup_of, d.dup_reason = orig.sha16, "same_body"
            # 월 간 동일 본문 = 같은 sha16(재수록) — dup_of 대신 prior_collection
            continue
        seen_sha[d.sha16] = d
        if d.published_at and d.fmt == "bi_story":
            k = (_title_key(d.title), d.published_at)
            if k in seen_key:
                d.dup_of, d.dup_reason = seen_key[k].sha16, "same_title_time"
                continue
            seen_key[k] = d
    uniq = [d for d in docs if d.dup_of is None]
    sets = {id(d): _line_set(d.body) for d in uniq}
    # 모음물 판본: 같은 컬렉션의 bi_web 문서끼리 상호 포함률 ≥ 0.9
    #   → 가장 늦은(동률이면 긴) 판본을 원본으로 둔다
    web = [d for d in uniq if d.fmt == "bi_web" and sets[id(d)]]
    for i, a in enumerate(web):
        for b in web[i + 1 :]:
            if a.yyyymm != b.yyyymm or a.dup_of or b.dup_of:
                continue
            sa, sb = sets[id(a)], sets[id(b)]
            inter = len(sa & sb)
            if min(inter / len(sa), inter / len(sb)) < NEAR_DUP_MUTUAL:
                continue
            keep, drop = sorted(
                (a, b), key=lambda d: (d.published_at or "", d.chars), reverse=True
            )
            drop.dup_of, drop.dup_reason = keep.sha16, "near_dup_compilation"
    # 원본이 다시 중복으로 밀려난 경우 사슬을 최종 원본으로 접는다
    by_sha = {d.sha16: d for d in docs}
    for d in docs:
        seen = set()
        while d.dup_of and d.dup_of in by_sha and by_sha[d.dup_of].dup_of:
            if d.dup_of in seen or by_sha[d.dup_of].dup_of == d.dup_of:
                break
            seen.add(d.dup_of)
            d.dup_of = by_sha[d.dup_of].dup_of
    # 조각: 헤더 없는 짧은 문서 또는 다른 문서에 줄 단위로 포함
    uniq = [d for d in docs if d.dup_of is None]
    for d in uniq:
        if d.fmt != "unknown":
            continue
        if d.chars < FRAGMENT_MIN_CHARS:
            d.fragment = True
            continue
        mine = sets[id(d)]
        if not mine:
            d.fragment = True
            continue
        for o in uniq:
            if o is d or o.fmt == "unknown":
                continue
            inter = len(mine & sets[id(o)])
            if inter / len(mine) >= FRAGMENT_CONTAIN:
                d.fragment, d.dup_of, d.dup_reason = True, o.sha16, "contained"
                break


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS europe_docs (
    sha16 TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    yyyymm TEXT NOT NULL,
    title TEXT NOT NULL,
    series TEXT NOT NULL,
    geo TEXT NOT NULL,
    groups_json TEXT NOT NULL,
    published_at TEXT,
    author TEXT,
    pages INTEGER,
    chars INTEGER,
    pdf_path TEXT NOT NULL,
    md_path TEXT NOT NULL,
    dup_of TEXT,
    fragment INTEGER NOT NULL DEFAULT 0,
    first_seen_collection TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS europe_doc_files (
    md_path TEXT PRIMARY KEY,
    sha16 TEXT NOT NULL,
    collection TEXT NOT NULL,
    mendeley_title TEXT,
    fmt TEXT
);
CREATE INDEX IF NOT EXISTS idx_europe_docs_yyyymm ON europe_docs(yyyymm);
CREATE INDEX IF NOT EXISTS idx_europe_doc_files_sha ON europe_doc_files(sha16);
"""
_EXTRA_COLS = {"fmt": "TEXT", "mendeley_title": "TEXT", "dup_reason": "TEXT"}


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(europe_docs)")}
    for c, decl in _EXTRA_COLS.items():
        if c not in cols:
            conn.execute(f"ALTER TABLE europe_docs ADD COLUMN {c} {decl}")


def upsert(conn: sqlite3.Connection, docs: list[Doc]) -> None:
    migrate(conn)
    first_seen: dict[str, str] = {}
    for d in sorted(docs, key=lambda d: d.yyyymm):
        first_seen.setdefault(d.sha16, d.collection)
    for d in sorted(docs, key=lambda d: d.yyyymm):
        # 같은 sha16이 여러 월에 있으면 최신 수록 월이 collection
        conn.execute(
            """INSERT INTO europe_docs(sha16,collection,yyyymm,title,series,geo,
            groups_json,published_at,author,pages,chars,pdf_path,md_path,dup_of,
            fragment,first_seen_collection,fmt,mendeley_title,dup_reason)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(sha16) DO UPDATE SET collection=excluded.collection,
            yyyymm=excluded.yyyymm,title=excluded.title,series=excluded.series,
            geo=excluded.geo,groups_json=excluded.groups_json,
            published_at=excluded.published_at,author=excluded.author,
            pages=excluded.pages,chars=excluded.chars,pdf_path=excluded.pdf_path,
            md_path=excluded.md_path,dup_of=excluded.dup_of,
            fragment=excluded.fragment,
            first_seen_collection=MIN(europe_docs.first_seen_collection,
                                      excluded.first_seen_collection),
            fmt=excluded.fmt,mendeley_title=excluded.mendeley_title,
            dup_reason=excluded.dup_reason""",
            (
                d.sha16,
                d.collection,
                d.yyyymm,
                d.title,
                d.series,
                d.geo,
                json.dumps(d.groups),
                d.published_at,
                d.author,
                d.pages,
                d.chars,
                d.pdf_path,
                d.md_path,
                d.dup_of,
                int(d.fragment),
                first_seen[d.sha16],
                d.fmt,
                d.mendeley_title,
                d.dup_reason,
            ),
        )
        conn.execute(
            """INSERT INTO europe_doc_files(md_path,sha16,collection,mendeley_title,fmt)
            VALUES(?,?,?,?,?) ON CONFLICT(md_path) DO UPDATE SET
            sha16=excluded.sha16,collection=excluded.collection,
            mendeley_title=excluded.mendeley_title,fmt=excluded.fmt""",
            (d.md_path, d.sha16, d.collection, d.mendeley_title, d.fmt),
        )


# ---------------------------------------------------------------------------
# 스캐폴드
# ---------------------------------------------------------------------------


def _collections(base: Path, upto: str) -> list[Path]:
    if not base.exists():
        return []
    return sorted(
        p for p in base.iterdir() if p.is_dir() and p.name.isdigit() and p.name <= upto
    )


def collect(edition: Edition, repo_root: Path) -> list[Doc]:
    docs: list[Doc] = []
    for folder in _collections(repo_root / EUROPE_DIR, edition.yyyymm):
        for md in sorted(folder.glob("*.md")):
            docs.append(load_doc(md, repo_root))
    mark_dups_and_fragments(docs)
    return docs


def load_card(sha: str, repo_root: Path) -> dict | None:
    p = repo_root / CARDS_DIR / f"{sha}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def session_docs(edition: Edition, docs: list[Doc]) -> list[Doc]:
    """당월 컬렉션 전량 + 전월 컬렉션 중 창 안 발행 문서(당월과 sha 중복 제외)."""
    cur = [d for d in docs if d.yyyymm == edition.yyyymm]
    cur_sha = {d.sha16 for d in cur}
    wfrom = edition.window["from"]
    extra = [
        d
        for d in docs
        if d.yyyymm < edition.yyyymm
        and d.date
        and d.date >= wfrom
        and d.sha16 not in cur_sha
    ]
    seen: set[str] = set()
    out = []
    for d in cur + extra:
        if d.md_path in seen:
            continue
        seen.add(d.md_path)
        out.append(d)
    return out


def card_target(d: Doc) -> str | None:
    """이 문서가 쓰는 카드의 sha16(조각 → None, 중복 → 원본)."""
    if d.fragment:
        return None
    return d.dup_of or d.sha16


def _prior_collection(d: Doc, docs: list[Doc]) -> str | None:
    """이 문서(또는 원본)가 더 이른 컬렉션에 이미 있었으면 그 컬렉션."""
    target = d.dup_of or d.sha16
    earlier = [
        o.collection
        for o in docs
        if o.yyyymm < d.yyyymm and (o.sha16 == target or o.sha16 == d.sha16)
    ]
    return min(earlier) if earlier else None


def _stale(d: Doc, edition: Edition) -> bool:
    if not d.date:
        return False
    lim = date.fromisoformat(edition.window["from"]) - timedelta(STALE_GRACE_DAYS)
    return d.date < lim.isoformat()


def build_session(edition: Edition, docs: list[Doc], repo_root: Path) -> dict:
    sdocs = session_docs(edition, docs)
    by_sha = {d.sha16: d for d in docs}
    entries, uncarded = [], []
    for d in sorted(sdocs, key=lambda d: (d.date or "", d.title)):
        tgt = card_target(d)
        card = load_card(tgt, repo_root) if tgt else None
        groups = d.groups
        if card and card.get("groups"):
            groups = [g for g in card["groups"] if g in GROUPS] or d.groups
        if tgt and card is None and tgt not in uncarded:
            uncarded.append(tgt)
        prior = _prior_collection(d, docs)
        entries.append(
            {
                "sha16": d.sha16,
                "series": d.series,
                "geo": d.geo,
                "groups": groups,
                "date": d.date,
                "published_at": d.published_at,
                "title": d.title,
                "author": d.author,
                "path": d.pdf_path,
                "md_path": d.md_path,
                "collection": d.collection,
                "card": card is not None,
                "card_sha16": tgt,
                "dup_of": d.dup_of,
                "dup_reason": d.dup_reason or None,
                "fragment": d.fragment,
                "prior_collection": prior,
                "stale": _stale(d, edition),
            }
        )
    # 원본이 세션 밖(전월)이면 by_sha로 존재만 확인
    for u in uncarded:
        assert u in by_sha, u
    groups_cov = []
    for g in GROUPS:
        gd = [e for e in entries if g in e["groups"] and not e["fragment"]]
        if not gd:
            continue
        groups_cov.append(
            {
                "group": g,
                "n_docs": len(gd),
                "section": f"sections/{g}.md",
                "latest_doc": max((e["date"] or "" for e in gd), default=None) or None,
            }
        )
    return {
        "session_type": "europe_monthly",
        "ticker": "EUROPE",
        "session_name": f"{edition.month} EUROPE MONTHLY",
        "collection": edition.collection,
        "period": {"from": edition.window["from"], "to": edition.window["to"]},
        "phase": edition.phase,
        "phases": {},
        "groups_covered": groups_cov,
        "documents": entries,
        "uncarded": uncarded,
        "data": {
            "chart_pack": "data/chart_pack.json",
            "table_pack": "data/table_pack.json",
        },
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pipeline_version": VERSION,
    }


# --- 마크다운 렌더 ---------------------------------------------------------


def _abs(repo_root: Path, rel: str) -> str:
    return str((repo_root / rel).resolve())


def _flags(e: dict) -> str:
    f = []
    if e["prior_collection"]:
        f.append("전월 재수록")
    if e["dup_of"] and not e["fragment"]:
        f.append("중복")
    if e["fragment"]:
        f.append("조각")
    if e["stale"]:
        f.append("창 이전 발행")
    return f" _({'·'.join(f)})_" if f else ""


def _card_bullets(card: dict | None, indent: str = "  ") -> list[str]:
    if not card:
        return [f"{indent}- (카드 대기)"]
    return [f"{indent}- {s}" for s in card.get("summary_ko", [])]


def _fmt_num(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def render_doc_cards(session: dict, repo_root: Path) -> str:
    ents = session["documents"]
    n_card = sum(1 for e in ents if e["card"])
    lines = [
        f"# {session['collection']} 문서 카드",
        "",
        f"- 기간 {session['period']['from']} ~ {session['period']['to']} · "
        f"문서 {len(ents)}건 · 카드 {n_card}건 · "
        f"카드 대기 {len(session['uncarded'])}건",
        "",
    ]
    titles = {e["sha16"]: e["title"] for e in ents if not e["dup_of"]}
    for g in GROUPS:
        ge = [e for e in ents if e["groups"] and e["groups"][0] == g]
        if not ge:
            continue
        lines += [f"## {g} — {GROUP_KO[g]} ({len(ge)}건)", ""]
        for e in sorted(ge, key=lambda e: e["published_at"] or ""):
            card = load_card(e["card_sha16"], repo_root) if e["card_sha16"] else None
            title = card.get("title_ko") if card else None
            lines.append(
                f"### {e['date'] or '날짜미상'} · {e['series']} · {e['title']}"
                f"{_flags(e)}"
            )
            meta = f"- 원문: [{e['title']}]({_abs(repo_root, e['path'])})"
            if title:
                meta += f" · {title}"
            lines.append(meta)
            if e["dup_of"] and not e["fragment"]:
                orig = titles.get(e["dup_of"], e["dup_of"])
                lines.append(f"  - 중복 문서 — 요지는 원본 카드 참조: {orig}")
                lines.append("")
                continue
            if e["prior_collection"]:
                lines.append(
                    f"  - {e['prior_collection']}에 이미 수록된 문서(요지 축약)"
                )
                lines += _card_bullets(card)[:2]
                lines.append("")
                continue
            if e["fragment"]:
                lines.append("  - 차트·캡션 조각 문서 (카드 없음)")
                lines.append("")
                continue
            lines += _card_bullets(card)
            if card and card.get("importance"):
                lines.append(f"  - 중요도 {card['importance']}/5")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_section(g: str, session: dict, repo_root: Path) -> str:
    ents = [e for e in session["documents"] if g in e["groups"] and not e["fragment"]]
    ents.sort(key=lambda e: e["published_at"] or "")
    main = [e for e in ents if not e["prior_collection"] and not e["dup_of"]]
    rerun = [e for e in ents if e["prior_collection"] or e["dup_of"]]
    lines = [
        f"# {GROUP_KO[g]} ({g}) — {session['collection']}",
        "",
        f"- 문서 {len(ents)}건(신규 {len(main)} · 재수록/중복 {len(rerun)})",
        "",
        "## 문서 목록",
        "",
        "| 발행일 | 계열 | 제목 | 원문 |",
        "|---|---|---|---|",
    ]
    for e in main:
        lines.append(
            f"| {e['date'] or ''} | {e['series']} | {e['title']} | "
            f"[pdf]({_abs(repo_root, e['path'])}) |"
        )
    if rerun:
        lines += ["", "### 전월 재수록·중복 (참고)", ""]
        for e in rerun:
            lines.append(
                f"- {e['date'] or ''} · {e['series']} · {e['title']}{_flags(e)} · "
                f"[pdf]({_abs(repo_root, e['path'])})"
            )
    lines += ["", "## 카드 요지", ""]
    nums: list[tuple[dict, dict]] = []
    for e in main:
        card = load_card(e["card_sha16"], repo_root) if e["card_sha16"] else None
        lines.append(f"### {e['date'] or ''} · {e['title']}")
        lines += _card_bullets(card, indent="")
        lines.append("")
        if card:
            for kn in card.get("key_numbers", []):
                if not kn.get("geo") or g in ("GLOBAL", "ENERGY_EXTERNAL", "EU_POLICY"):
                    nums.append((e, kn))
                elif _geo_fits(g, kn.get("geo", "")):
                    nums.append((e, kn))
    prior = [e for e in rerun if e["prior_collection"] and not e["dup_of"]]
    if prior:
        lines += ["### 전월 재수록 문서 요지 (축약)", ""]
        for e in prior:
            card = load_card(e["card_sha16"], repo_root) if e["card_sha16"] else None
            lines.append(f"- {e['date'] or ''} · {e['title']}")
            lines += _card_bullets(card)[:2]
        lines.append("")
    lines += [
        "## 핵심 수치",
        "",
        "| 지표 | 지역 | 기간 | 값 | 단위 | 구분 | 출처(발행일) |",
        "|---|---|---|---|---|---|---|",
    ]
    for e, kn in nums:
        lines.append(
            f"| {kn.get('metric', '')} | {kn.get('geo', '')} | {kn.get('period', '')} "
            f"| {_fmt_num(kn.get('value'))} | {kn.get('unit', '')} | "
            f"{kn.get('kind', '')} | {e['title'][:48]} ({e['date'] or ''}) |"
        )
    if not nums:
        lines.append("| (카드 대기) | | | | | | |")
    lines.append("")
    return "\n".join(lines)


_GROUP_GEOS = {
    "ECB": {"EA", "ECB", "EU"},
    "EA_MACRO": {"EA", "EU", "ECB"},
    "DE": {"DE"},
    "FR": {"FR"},
    "IT": {"IT"},
    "ES": {"ES"},
    "UK": {"UK", "GB"},
}


def _geo_fits(g: str, geo: str) -> bool:
    allowed = _GROUP_GEOS.get(g)
    return True if allowed is None else geo.upper() in allowed


def _write_section(path: Path, scaffold_text: str) -> None:
    tail = NARRATIVE + "\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if SCAFFOLD_END in old:
            tail = old.split(SCAFFOLD_END, 1)[1].lstrip("\n") or tail
    path.write_text(
        scaffold_text.rstrip() + f"\n\n{SCAFFOLD_END}\n\n" + tail, encoding="utf-8"
    )


def scaffold(
    edition: Edition,
    *,
    repo_root: Path | None = None,
    db_path: Path | None = None,
) -> dict:
    repo_root = Path(repo_root or REPO_ROOT)
    docs = collect(edition, repo_root)
    dbp = repo_root / (db_path or DB_PATH)
    dbp.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(dbp, timeout=10) as conn:
        upsert(conn, docs)
    session = build_session(edition, docs, repo_root)
    root = repo_root / edition.root
    (root / "documents").mkdir(parents=True, exist_ok=True)
    (root / "sections").mkdir(parents=True, exist_ok=True)
    (root / "documents" / "doc_cards.md").write_text(
        render_doc_cards(session, repo_root), encoding="utf-8"
    )
    for gc in session["groups_covered"]:
        _write_section(
            root / gc["section"], render_section(gc["group"], session, repo_root)
        )
    (root / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return session


def summarize(session: dict, docs: list[Doc] | None = None) -> str:
    ents = session["documents"]
    cur = [e for e in ents if e["collection"] == session["collection"]]
    return json.dumps(
        {
            "documents": len(ents),
            "current_collection": len(cur),
            "from_prior_collection_in_window": len(ents) - len(cur),
            "dup_within": sum(1 for e in ents if e["dup_of"] and not e["fragment"]),
            "prior_collection_repeats": sum(1 for e in ents if e["prior_collection"]),
            "fragments": sum(1 for e in ents if e["fragment"]),
            "stale": sum(1 for e in ents if e["stale"]),
            "carded": sum(1 for e in ents if e["card"]),
            "uncarded": len(session["uncarded"]),
            "groups": {g["group"]: g["n_docs"] for g in session["groups_covered"]},
            "primary_groups": _primary_counts(ents),
        },
        ensure_ascii=False,
        indent=1,
    )


def _primary_counts(ents: list[dict]) -> dict:
    out: dict[str, int] = {}
    for e in ents:
        if e["groups"]:
            out[e["groups"][0]] = out.get(e["groups"][0], 0) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="monthly_brief.intake")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scaffold")
    s.add_argument("--month", required=True)
    s.add_argument("--root", default="")
    s.add_argument("--as-of", default="")
    a = ap.parse_args(argv)
    ed = load_edition(REPO_ROOT / a.root if a.root else REPO_ROOT / BASE_DIR / a.month)
    if a.as_of:
        ed.as_of = a.as_of
        ed.window = {**ed.window, "to": a.as_of}
    session = scaffold(ed)
    print(summarize(session))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
