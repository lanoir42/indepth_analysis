"""KCIF 스토어 — references.db 확장 (report_texts + FTS5 + 토픽 타임라인).

telegram의 topic_tracker 스토어를 미러하되 소스 단위가 '메시지'가 아니라
'KCIF 리포트'다. 설계 결정:

- **워터마크 = report_texts.id (적재 순 단조)**. reports.id는 카탈로그 순서라
  다운로드 실패→재시도, restricted 해제, 늦은 백필로 published_date/적재
  순서가 역전될 수 있다. report_texts.id는 텍스트가 실제로 준비된 순서라
  늦게 도착한 본문도 반드시 커서 앞에 놓인다.
- FK 미선언 + 명시적 cascade (telegram과 동일 — delete_topic이 한 트랜잭션에서
  3테이블 삭제).
- busy_timeout 5000ms: 18:00 launchd 잡과 수동 CLI의 짧은 경합 흡수.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata

from indepth_analysis.kcif.paths import DB_PATH

ACTIVE_TOPIC_CAP = 12
EVENTS_PER_DAY_CAP = 8
EVIDENCE_EXCERPT_CHARS = 300

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH))
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.execute("PRAGMA busy_timeout=5000")
        migrate(_conn)
    return _conn


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r["name"] == col for r in conn.execute(f"PRAGMA table_info({table})"))


def migrate(conn: sqlite3.Connection) -> None:
    """Idempotent — 기존 references.db 스키마(ReferenceDB)를 전제로 확장만 한다."""
    # reports 컬럼 확장 (기존 ReferenceDB SCHEMA_SQL은 건드리지 않는다)
    if not _has_column(conn, "reports", "md_path"):
        conn.execute("ALTER TABLE reports ADD COLUMN md_path TEXT")
    if not _has_column(conn, "reports", "file_url"):
        conn.execute("ALTER TABLE reports ADD COLUMN file_url TEXT")

    conn.executescript("""
CREATE TABLE IF NOT EXISTS report_texts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL UNIQUE,
    text TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    created_ts REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS report_texts_fts USING fts5(
    text,
    content='report_texts',
    content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS report_texts_ai AFTER INSERT ON report_texts BEGIN
    INSERT INTO report_texts_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS report_texts_ad AFTER DELETE ON report_texts BEGIN
    INSERT INTO report_texts_fts(report_texts_fts, rowid, text)
    VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS report_texts_au AFTER UPDATE OF text ON report_texts BEGIN
    INSERT INTO report_texts_fts(report_texts_fts, rowid, text)
    VALUES ('delete', old.id, old.text);
    INSERT INTO report_texts_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS kcif_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    keywords_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    summary_text TEXT,
    summary_ts REAL,
    created_ts REAL NOT NULL,
    archived_ts REAL,
    last_event_ts REAL,
    watermark_id INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kcif_topic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    event_date TEXT NOT NULL,
    ts REAL NOT NULL,
    headline TEXT NOT NULL,
    detail TEXT,
    report_ids_json TEXT NOT NULL DEFAULT '[]',
    created_ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kcif_topic_events_topic_date
    ON kcif_topic_events(topic_id, event_date);

CREATE TABLE IF NOT EXISTS kcif_topic_evidence (
    topic_id INTEGER NOT NULL,
    report_id INTEGER NOT NULL,
    matched_ts REAL NOT NULL,
    PRIMARY KEY (topic_id, report_id)
);
""")
    conn.commit()


# ── report texts ───────────────────────────────────────────────────────────

def initialize_daily_text_delivery() -> bool:
    conn = get_conn()
    if not _has_column(conn, "report_texts", "id"):
        return False
    conn.execute("CREATE TABLE IF NOT EXISTS kcif_daily_text_cursor (singleton INTEGER PRIMARY KEY, baseline_id INTEGER NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS kcif_daily_text_delivery (text_id INTEGER PRIMARY KEY, report_date TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO kcif_daily_text_cursor VALUES (1, (SELECT COALESCE(MAX(id), 0) FROM report_texts))")
    conn.commit()
    return True


def pending_daily_texts(report_date: str, window_start: str, cap: int = 30) -> list[dict]:
    conn = get_conn()
    if not _has_column(conn, "kcif_daily_text_cursor", "baseline_id"):
        return []
    return [dict(row) for row in conn.execute(
        "SELECT t.id AS text_id, t.text, r.id, r.title, r.category, r.md_path, r.published_date "
        "FROM report_texts t JOIN reports r ON r.id=t.report_id "
        "LEFT JOIN kcif_daily_text_delivery d ON d.text_id=t.id "
        "WHERE t.id > (SELECT baseline_id FROM kcif_daily_text_cursor WHERE singleton=1) "
        "AND COALESCE(r.published_date, '') != '' AND r.published_date < ? "
        "AND (d.text_id IS NULL OR d.report_date=?) "
        "ORDER BY t.id LIMIT ?", (window_start, report_date, cap)
    ).fetchall()]


def mark_daily_texts(report_date: str, report_ids: list[int], late_text_ids: list[int]) -> None:
    conn = get_conn()
    if not _has_column(conn, "kcif_daily_text_cursor", "baseline_id"):
        return
    text_ids = list(late_text_ids)
    if report_ids:
        marks = ",".join("?" for _ in report_ids)
        text_ids.extend(row[0] for row in conn.execute(
            f"SELECT id FROM report_texts WHERE report_id IN ({marks})", report_ids))
    conn.executemany("INSERT OR IGNORE INTO kcif_daily_text_delivery VALUES (?, ?)",
                     [(text_id, report_date) for text_id in text_ids])
    conn.commit()


def upsert_report_text(report_id: int, text: str, *, md_path: str | None = None) -> int:
    """본문 미러 적재. 재추출 시 새 id를 받아 토픽 스캔에 다시 노출된다(의도)."""
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM report_texts WHERE report_id = ?", (report_id,))
        cur = conn.execute(
            "INSERT INTO report_texts (report_id, text, char_count, created_ts) "
            "VALUES (?, ?, ?, ?)",
            (report_id, text, len(text), time.time()),
        )
        if md_path is not None:
            conn.execute("UPDATE reports SET md_path = ? WHERE id = ?", (md_path, report_id))
    return int(cur.lastrowid)


def max_text_id() -> int:
    row = get_conn().execute("SELECT COALESCE(MAX(id), 0) AS m FROM report_texts").fetchone()
    return int(row["m"])


def text_id_before_date(published_date_cutoff: str) -> int:
    """published_date < cutoff 인 텍스트들의 최대 id — 시드 워터마크 초기화용."""
    row = get_conn().execute(
        "SELECT COALESCE(MAX(t.id), 0) AS m FROM report_texts t "
        "JOIN reports r ON r.id = t.report_id "
        "WHERE COALESCE(r.published_date, '') < ?",
        (published_date_cutoff,),
    ).fetchone()
    return int(row["m"])


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def scan_candidates(topic: dict, cap: int = 40) -> list[dict]:
    """키워드 LIKE 매칭 신규 후보 (id > watermark_id, 미평가분만)."""
    keywords = [k for k in (topic.get("keywords") or []) if k]
    if not keywords:
        return []
    likes = " OR ".join("lower(t.text) LIKE ? ESCAPE '\\'" for _ in keywords)
    params: list = [f"%{_like_escape(k.lower())}%" for k in keywords]
    params += [int(topic.get("watermark_id") or 0), topic["id"], cap]
    rows = get_conn().execute(
        f"SELECT t.id AS text_id, t.report_id, r.title, r.category, "
        f"       r.published_date, r.md_path, t.text "
        f"FROM report_texts t JOIN reports r ON r.id = t.report_id "
        f"WHERE ({likes}) AND t.id > ? "
        f"  AND t.report_id NOT IN "
        f"      (SELECT report_id FROM kcif_topic_evidence WHERE topic_id = ?) "
        f"ORDER BY t.id ASC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def search_texts(query: str, *, since: str | None = None, until: str | None = None,
                 category: str | None = None, limit: int = 30) -> list[dict]:
    """FTS(3자+ MATCH, bm25) + 짧은 키워드 LIKE 폴백 — tg-sum find와 동일 규칙."""
    terms = [t for t in query.split() if t]
    match_terms = [t for t in terms if len(t) >= 3]
    like_terms = [t for t in terms if len(t) < 3]

    where: list[str] = []
    params: list = []
    if since:
        where.append("COALESCE(r.published_date,'') >= ?")
        params.append(since)
    if until:
        where.append("COALESCE(r.published_date,'') < ?")
        params.append(until)
    if category:
        where.append("r.category LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(category)}%")
    for t in like_terms:
        where.append("t.text LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(t)}%")

    conn = get_conn()
    if match_terms:
        expr = " AND ".join('"' + t.replace('"', '""') + '"' for t in match_terms)
        sql = ("SELECT r.id, r.title, r.category, r.published_date, r.md_path, "
               "bm25(report_texts_fts) AS rank "
               "FROM report_texts_fts f "
               "JOIN report_texts t ON t.id = f.rowid "
               "JOIN reports r ON r.id = t.report_id "
               "WHERE report_texts_fts MATCH ?")
        params = [expr, *params]
        if where:
            sql += " AND " + " AND ".join(where)
        sql += " ORDER BY rank, r.published_date DESC LIMIT ?"
    else:
        sql = ("SELECT r.id, r.title, r.category, r.published_date, r.md_path, "
               "NULL AS rank "
               "FROM report_texts t JOIN reports r ON r.id = t.report_id")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY r.published_date DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ── topics (telegram tracked_topics 미러) ──────────────────────────────────

def slugify(title: str) -> str:
    t = unicodedata.normalize("NFC", title.strip())
    t = re.sub(r"[^\w가-힣]+", "-", t).strip("-").lower()
    return t or "topic"


def _topic_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["keywords"] = json.loads(d.pop("keywords_json") or "[]")
    except (ValueError, TypeError):
        d.pop("keywords_json", None)
        d["keywords"] = []
    return d


def create_topic(title: str, description: str | None = None,
                 keywords: list[str] | None = None,
                 watermark_id: int = 0) -> dict:
    conn = get_conn()
    slug = slugify(title)
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM kcif_topics WHERE status='active'").fetchone()["n"]
    if n >= ACTIVE_TOPIC_CAP:
        raise ValueError(f"active topic cap ({ACTIVE_TOPIC_CAP}) reached")
    if conn.execute("SELECT 1 FROM kcif_topics WHERE slug = ?", (slug,)).fetchone():
        raise ValueError(f"duplicate slug: {slug}")
    conn.execute(
        "INSERT INTO kcif_topics (slug, title, description, keywords_json, "
        "created_ts, watermark_id) VALUES (?, ?, ?, ?, ?, ?)",
        (slug, title.strip(), description, json.dumps(keywords or [], ensure_ascii=False),
         time.time(), int(watermark_id)),
    )
    conn.commit()
    return get_topic(slug)  # type: ignore[return-value]


def get_topic(slug: str) -> dict | None:
    row = get_conn().execute("SELECT * FROM kcif_topics WHERE slug = ?", (slug,)).fetchone()
    return _topic_to_dict(row) if row else None


def list_topics(status: str | None = None) -> list[dict]:
    if status:
        rows = get_conn().execute(
            "SELECT * FROM kcif_topics WHERE status = ? ORDER BY id ASC", (status,)).fetchall()
    else:
        rows = get_conn().execute("SELECT * FROM kcif_topics ORDER BY id ASC").fetchall()
    return [_topic_to_dict(r) for r in rows]


def set_keywords(slug: str, keywords: list[str]) -> None:
    conn = get_conn()
    conn.execute("UPDATE kcif_topics SET keywords_json = ? WHERE slug = ?",
                 (json.dumps(keywords, ensure_ascii=False), slug))
    conn.commit()


def set_status(slug: str, status: str) -> None:
    conn = get_conn()
    if status == "active":
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM kcif_topics WHERE status='active'").fetchone()["n"]
        if n >= ACTIVE_TOPIC_CAP:
            raise ValueError(f"active topic cap ({ACTIVE_TOPIC_CAP}) reached")
        conn.execute("UPDATE kcif_topics SET status='active', archived_ts=NULL "
                     "WHERE slug = ?", (slug,))
    else:
        conn.execute("UPDATE kcif_topics SET status='archived', archived_ts=? "
                     "WHERE slug = ?", (time.time(), slug))
    conn.commit()


def delete_topic(slug: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT id FROM kcif_topics WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return False
    tid = int(row["id"])
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM kcif_topic_evidence WHERE topic_id = ?", (tid,))
        conn.execute("DELETE FROM kcif_topic_events WHERE topic_id = ?", (tid,))
        conn.execute("DELETE FROM kcif_topics WHERE id = ?", (tid,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def add_evidence(slug: str, report_ids: list[int]) -> int:
    conn = get_conn()
    t = get_topic(slug)
    if not t:
        return 0
    now = time.time()
    added = 0
    for rid in report_ids:
        cur = conn.execute(
            "INSERT OR IGNORE INTO kcif_topic_evidence (topic_id, report_id, matched_ts) "
            "VALUES (?, ?, ?)", (t["id"], int(rid), now))
        added += cur.rowcount
    conn.commit()
    return added


def add_events(slug: str, events: list[dict]) -> int:
    """이벤트 추가 — (topic, event_date)당 EVENTS_PER_DAY_CAP 초과분은 드롭."""
    conn = get_conn()
    t = get_topic(slug)
    if not t:
        return 0
    now = time.time()
    added = 0
    max_ts = float(t.get("last_event_ts") or 0)
    for e in events:
        day = e["event_date"]
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM kcif_topic_events "
            "WHERE topic_id = ? AND event_date = ?", (t["id"], day)).fetchone()["n"]
        if n >= EVENTS_PER_DAY_CAP:
            continue
        ts = float(e.get("ts") or now)
        conn.execute(
            "INSERT INTO kcif_topic_events (topic_id, event_date, ts, headline, "
            "detail, report_ids_json, created_ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (t["id"], day, ts, e["headline"][:120], (e.get("detail") or "")[:300],
             json.dumps(e.get("report_ids") or [], ensure_ascii=False), now))
        added += 1
        max_ts = max(max_ts, ts)
    if added:
        conn.execute("UPDATE kcif_topics SET last_event_ts = MAX(COALESCE(last_event_ts,0), ?) "
                     "WHERE id = ?", (max_ts, t["id"]))
    conn.commit()
    return added


# 요약 저장 상한. 프롬프트가 요구하는 600자보다 넉넉하게 둔다 — 폭주 방지가
# 목적이지 편집이 목적이 아니다. 2026-08-26 이전에는 500자에서 무조건 잘랐는데,
# 요약이 리포트의 **본문**이 되면서(한 줄 요약 폐기) 문장이 반토막 나는 게
# 그대로 드러났다("…국채 바이백 규모를 $2").
SUMMARY_MAX_CHARS = 900


def _cut_at_sentence(text: str, limit: int) -> str:
    """Trim to `limit` on a sentence boundary — never mid-word.

    A summary that ends "…규모를 $2" reads as data loss; one that ends a
    sentence early reads as a summary.
    """
    if len(text) <= limit:
        return text
    head = text[:limit]
    for end in ("다. ", "다.\n", "요. ", "니다. ", ". "):
        i = head.rfind(end)
        if i > limit * 0.5:
            return head[: i + len(end)].rstrip()
    i = max(head.rfind("다."), head.rfind("."))
    if i > limit * 0.5:
        return head[: i + 1]
    return head.rstrip() + "…"


def update_summary(slug: str, summary: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE kcif_topics SET summary_text = ?, summary_ts = ? WHERE slug = ?",
                 (_cut_at_sentence(summary, SUMMARY_MAX_CHARS), time.time(), slug))
    conn.commit()


def advance_watermark(slug: str, new_id: int) -> None:
    """단조 전진만 허용."""
    conn = get_conn()
    conn.execute("UPDATE kcif_topics SET watermark_id = ? "
                 "WHERE slug = ? AND ? > watermark_id", (int(new_id), slug, int(new_id)))
    conn.commit()


def timeline(slug: str) -> list[dict]:
    t = get_topic(slug)
    if not t:
        return []
    rows = get_conn().execute(
        "SELECT * FROM kcif_topic_events WHERE topic_id = ? ORDER BY event_date ASC, id ASC",
        (t["id"],)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["report_ids"] = json.loads(d.pop("report_ids_json") or "[]")
        except (ValueError, TypeError):
            d["report_ids"] = []
        out.append(d)
    return out


def evidence_stats(slug: str, top_categories: int = 3) -> dict:
    t = get_topic(slug)
    if not t:
        return {"total": 0, "categories": []}
    total = get_conn().execute(
        "SELECT COUNT(*) AS n FROM kcif_topic_evidence WHERE topic_id = ?",
        (t["id"],)).fetchone()["n"]
    rows = get_conn().execute(
        "SELECT COALESCE(NULLIF(r.category,''),'기타') AS cat, COUNT(*) AS n "
        "FROM kcif_topic_evidence e JOIN reports r ON r.id = e.report_id "
        "WHERE e.topic_id = ? GROUP BY cat ORDER BY n DESC LIMIT ?",
        (t["id"], top_categories)).fetchall()
    return {"total": total, "categories": [(r["cat"], r["n"]) for r in rows]}


def evidence_with_reports(slug: str, limit: int = 30) -> list[dict]:
    t = get_topic(slug)
    if not t:
        return []
    rows = get_conn().execute(
        "SELECT e.report_id, e.matched_ts, r.title, r.category, r.published_date, "
        "       r.md_path, r.url "
        "FROM kcif_topic_evidence e JOIN reports r ON r.id = e.report_id "
        "WHERE e.topic_id = ? "
        "ORDER BY COALESCE(r.published_date,'') DESC, e.report_id DESC LIMIT ?",
        (t["id"], int(limit))).fetchall()
    return [dict(r) for r in rows]
