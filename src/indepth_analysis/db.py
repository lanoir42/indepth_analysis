import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from indepth_analysis.models.reference import (
    Chunk,
    DownloadStatus,
    ProcessingStatus,
    Report,
    Source,
)

logger = logging.getLogger(__name__)

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    base_url TEXT NOT NULL,
    last_scraped_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT DEFAULT '',
    author TEXT DEFAULT '',
    published_date TEXT,
    url TEXT NOT NULL,
    file_name TEXT,
    file_size_bytes INTEGER,
    file_hash TEXT,
    download_status TEXT NOT NULL DEFAULT 'pending',
    download_error TEXT,
    processing_status TEXT NOT NULL DEFAULT 'unprocessed',
    page_count INTEGER,
    extraction_method TEXT,
    extraction_cost_usd REAL DEFAULT 0.0,
    embedding_cost_usd REAL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, external_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    token_count INTEGER,
    is_table INTEGER NOT NULL DEFAULT 0,
    embedding BLOB,
    embedding_model TEXT,
    UNIQUE(report_id, chunk_index)
);

CREATE VIEW IF NOT EXISTS cost_summary AS
SELECT s.name, COUNT(r.id) AS total,
    SUM(CASE WHEN r.download_status='downloaded' THEN 1 ELSE 0 END) AS downloaded,
    SUM(CASE WHEN r.processing_status='embedded' THEN 1 ELSE 0 END) AS embedded,
    ROUND(SUM(r.extraction_cost_usd + r.embedding_cost_usd), 4) AS total_cost
FROM reports r JOIN sources s ON r.source_id = s.id GROUP BY s.name;
"""

DEFAULT_DB_DIR = Path("references")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class ReferenceDB:
    """SQLite connection manager for the references database."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (DEFAULT_DB_DIR / "references.db")
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        cursor = self.conn.executescript(SCHEMA_SQL)
        cursor.close()
        self.conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- Sources ---

    def get_or_create_source(self, name: str, base_url: str) -> Source:
        row = self.conn.execute(
            "SELECT * FROM sources WHERE name = ?", (name,)
        ).fetchone()
        if row:
            return Source(**dict(row))
        self.conn.execute(
            "INSERT INTO sources (name, base_url) VALUES (?, ?)",
            (name, base_url),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM sources WHERE name = ?", (name,)
        ).fetchone()
        return Source(**dict(row))

    def update_source_scraped(self, source_id: int) -> None:
        self.conn.execute(
            "UPDATE sources SET last_scraped_at = ? WHERE id = ?",
            (_now(), source_id),
        )
        self.conn.commit()

    # --- Reports ---

    def upsert_report(self, report: Report) -> Report:
        existing = self.conn.execute(
            "SELECT id FROM reports WHERE source_id = ? AND external_id = ?",
            (report.source_id, report.external_id),
        ).fetchone()
        if existing:
            report.id = existing["id"]
            return report

        self.conn.execute(
            """INSERT INTO reports
            (source_id, external_id, title, category, author,
             published_date, url, file_name, download_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.source_id,
                report.external_id,
                report.title,
                report.category,
                report.author,
                report.published_date,
                report.url,
                report.file_name,
                report.download_status.value,
            ),
        )
        self.conn.commit()
        report.id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return report

    def update_report_download(
        self,
        report_id: int,
        *,
        status: DownloadStatus,
        file_name: str | None = None,
        file_size_bytes: int | None = None,
        file_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """UPDATE reports SET
                download_status = ?, file_name = COALESCE(?, file_name),
                file_size_bytes = COALESCE(?, file_size_bytes),
                file_hash = COALESCE(?, file_hash),
                download_error = ?
            WHERE id = ?""",
            (status.value, file_name, file_size_bytes, file_hash, error, report_id),
        )
        self.conn.commit()

    def update_report_processing(
        self,
        report_id: int,
        *,
        status: ProcessingStatus,
        page_count: int | None = None,
        extraction_method: str | None = None,
        extraction_cost_usd: float | None = None,
        embedding_cost_usd: float | None = None,
    ) -> None:
        self.conn.execute(
            """UPDATE reports SET
                processing_status = ?,
                page_count = COALESCE(?, page_count),
                extraction_method = COALESCE(?, extraction_method),
                extraction_cost_usd = COALESCE(?, extraction_cost_usd),
                embedding_cost_usd = COALESCE(?, embedding_cost_usd)
            WHERE id = ?""",
            (
                status.value,
                page_count,
                extraction_method,
                extraction_cost_usd,
                embedding_cost_usd,
                report_id,
            ),
        )
        self.conn.commit()

    def get_reports(
        self,
        *,
        source_id: int | None = None,
        download_status: DownloadStatus | None = None,
        processing_status: ProcessingStatus | None = None,
    ) -> list[Report]:
        query = "SELECT * FROM reports WHERE 1=1"
        params: list = []
        if source_id is not None:
            query += " AND source_id = ?"
            params.append(source_id)
        if download_status is not None:
            query += " AND download_status = ?"
            params.append(download_status.value)
        if processing_status is not None:
            query += " AND processing_status = ?"
            params.append(processing_status.value)
        query += " ORDER BY published_date DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [Report(**dict(r)) for r in rows]

    def get_report_by_id(self, report_id: int) -> Report | None:
        row = self.conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return Report(**dict(row)) if row else None

    # --- Chunks ---

    def insert_chunks(self, chunks: list[Chunk]) -> None:
        self.conn.executemany(
            """INSERT OR REPLACE INTO chunks
            (report_id, chunk_index, content, page_start, page_end,
             token_count, is_table, embedding, embedding_model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    c.report_id,
                    c.chunk_index,
                    c.content,
                    c.page_start,
                    c.page_end,
                    c.token_count,
                    int(c.is_table),
                    c.embedding,
                    c.embedding_model,
                )
                for c in chunks
            ],
        )
        self.conn.commit()

    def get_chunks(
        self,
        *,
        report_id: int | None = None,
        with_embeddings: bool = False,
    ) -> list[Chunk]:
        cols = (
            "*"
            if with_embeddings
            else (
                "id, report_id, chunk_index, content, page_start, page_end, "
                "token_count, is_table, embedding_model"
            )
        )
        query = f"SELECT {cols} FROM chunks"
        params: list = []
        if report_id is not None:
            query += " WHERE report_id = ?"
            params.append(report_id)
        query += " ORDER BY report_id, chunk_index"
        rows = self.conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["is_table"] = bool(d.get("is_table", 0))
            if not with_embeddings and "embedding" not in d:
                d["embedding"] = None
            results.append(Chunk(**d))
        return results

    def get_all_embedded_chunks(self) -> list[tuple[Chunk, bytes]]:
        """Return chunks that have embeddings, along with their embedding bytes."""
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE embedding IS NOT NULL "
            "ORDER BY report_id, chunk_index"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            emb = d.pop("embedding")
            d["is_table"] = bool(d.get("is_table", 0))
            d["embedding"] = None
            results.append((Chunk(**d), emb))
        return results

    # --- Status / Cost ---

    def get_cost_summary(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM cost_summary").fetchall()
        return [dict(r) for r in rows]

    def get_status_summary(self) -> dict:
        sources = self.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        reports = self.conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        chunks = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded = self.conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()[0]

        status_counts = {}
        for row in self.conn.execute(
            "SELECT download_status, COUNT(*) as cnt "
            "FROM reports GROUP BY download_status"
        ).fetchall():
            status_counts[row["download_status"]] = row["cnt"]

        proc_counts = {}
        for row in self.conn.execute(
            "SELECT processing_status, COUNT(*) as cnt "
            "FROM reports GROUP BY processing_status"
        ).fetchall():
            proc_counts[row["processing_status"]] = row["cnt"]

        return {
            "sources": sources,
            "reports": reports,
            "chunks": chunks,
            "embedded_chunks": embedded,
            "download_status": status_counts,
            "processing_status": proc_counts,
        }
