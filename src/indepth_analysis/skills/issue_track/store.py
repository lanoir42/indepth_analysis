"""Persistent storage for issue tracking — SQLite + ChromaDB."""

import hashlib
import json
import logging
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from indepth_analysis.models.issue_track import Evidence, IssueRun

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.0"

_STRIP_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "ref",
        "share",
        "fbclid",
        "gclid",
        "msclkid",
        "twclid",
        "_ga",
        "mc_cid",
        "mc_eid",
    }
)

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS issue_topics (
    slug              TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    description       TEXT,
    created_at        TEXT NOT NULL,
    last_run_at       TEXT,
    seed_keywords     TEXT
);

CREATE TABLE IF NOT EXISTS issue_runs (
    run_id            TEXT PRIMARY KEY,
    slug              TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    model_used        TEXT,
    total_evidence    INTEGER DEFAULT 0,
    new_evidence      INTEGER DEFAULT 0,
    report_path       TEXT,
    pipeline_version  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_issue_runs_slug ON issue_runs(slug);

CREATE TABLE IF NOT EXISTS issue_evidence (
    evidence_id       TEXT PRIMARY KEY,
    slug              TEXT NOT NULL,
    first_seen_run    TEXT NOT NULL,
    last_seen_run     TEXT NOT NULL,
    seen_count        INTEGER NOT NULL DEFAULT 1,
    tier              INTEGER NOT NULL,
    source_type       TEXT NOT NULL,
    source_name       TEXT,
    source_handle     TEXT,
    canonical_url     TEXT NOT NULL,
    title             TEXT,
    excerpt           TEXT,
    full_text_hash    TEXT,
    published_at      TEXT,
    fetched_at        TEXT NOT NULL,
    language          TEXT,
    stance            TEXT DEFAULT 'neutral',
    credibility_score REAL,
    credibility_basis TEXT,
    raw_payload       TEXT
);

CREATE INDEX IF NOT EXISTS idx_issue_evidence_slug ON issue_evidence(slug);
CREATE INDEX IF NOT EXISTS idx_issue_evidence_url ON issue_evidence(canonical_url);
CREATE INDEX IF NOT EXISTS idx_issue_evidence_tier ON issue_evidence(slug, tier);

CREATE TABLE IF NOT EXISTS issue_source_credibility (
    source_handle     TEXT PRIMARY KEY,
    source_type       TEXT NOT NULL,
    display_name      TEXT,
    score             REAL NOT NULL,
    rubric_json       TEXT NOT NULL,
    rationale         TEXT,
    evaluated_at      TEXT NOT NULL,
    evaluator_model   TEXT
);
"""


def canonicalize_url(url: str) -> str:
    if not url:
        return url
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned = {k: v for k, v in params.items() if k.lower() not in _STRIP_PARAMS}
        new_query = urlencode(cleaned, doseq=True)
        normalized = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            query=new_query,
            fragment="",
        )
        return urlunparse(normalized).rstrip("/")
    except Exception:
        return url


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_evidence_id(canonical_url: str, text_hash: str | None = None) -> str:
    key = canonical_url + (text_hash or "")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _default_db_path() -> Path:
    env = os.environ.get("TELEGRAM_CACHE_DB_PATH")
    if env:
        return Path(env)
    return Path.home() / "projects" / "telegram" / "cache.db"


def _default_chroma_path() -> Path:
    env = os.environ.get("TELEGRAM_CHROMA_PATH")
    if env:
        return Path(env)
    return Path.home() / "projects" / "telegram" / "chroma_db"


class IssueStore:
    def __init__(
        self,
        db_path: Path | None = None,
        chroma_path: Path | None = None,
    ) -> None:
        self.db_path = db_path or _default_db_path()
        self.chroma_path = chroma_path or _default_chroma_path()
        self._conn: sqlite3.Connection | None = None
        self._chroma_collection = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        return self._conn

    def _get_chroma_collection(self):
        if self._chroma_collection is not None:
            return self._chroma_collection
        try:
            import chromadb
            from chromadb import Documents, EmbeddingFunction, Embeddings
            from google import genai as google_genai

            api_key = os.environ.get("GOOGLE_API_KEY", "")

            class _GeminiEmbed(EmbeddingFunction):
                def __call__(self, input: Documents) -> Embeddings:
                    client = google_genai.Client(api_key=api_key)
                    result = client.models.embed_content(
                        model="gemini-embedding-001",
                        contents=list(input),
                    )
                    return [e.values for e in result.embeddings]

            chroma_client = chromadb.PersistentClient(path=str(self.chroma_path))
            self._chroma_collection = chroma_client.get_or_create_collection(
                name="issue_tracking",
                embedding_function=_GeminiEmbed(),
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError as e:
            logger.warning("ChromaDB/google-genai not available — skipping: %s", e)
        except Exception as e:
            logger.warning("ChromaDB init failed — skipping: %s", e)
        return self._chroma_collection

    def ensure_topic(
        self, slug: str, title: str, description: str = ""
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO issue_topics (slug, title, description, created_at) VALUES (?, ?, ?, ?)",
            (slug, title, description, now),
        )
        self.conn.commit()

    def update_topic_last_run(self, slug: str) -> None:
        self.conn.execute(
            "UPDATE issue_topics SET last_run_at = ? WHERE slug = ?",
            (datetime.now(UTC).isoformat(), slug),
        )
        self.conn.commit()

    def upsert_run(self, run: IssueRun) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO issue_runs
               (run_id, slug, started_at, finished_at, model_used,
                total_evidence, new_evidence, report_path, pipeline_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.run_id,
                run.slug,
                run.started_at,
                run.finished_at,
                run.model_used,
                run.total_evidence,
                run.new_evidence,
                run.report_path,
                run.pipeline_version,
            ),
        )
        self.conn.commit()

    def upsert_evidence(
        self, evidence: Evidence, current_run_id: str
    ) -> tuple[bool, Evidence]:
        """Insert or update evidence. Returns (is_new, stored_evidence)."""
        url = canonicalize_url(evidence.canonical_url)
        text_hash = evidence.full_text_hash

        row = self.conn.execute(
            "SELECT * FROM issue_evidence WHERE canonical_url = ? AND slug = ?",
            (url, evidence.slug),
        ).fetchone()

        now_iso = datetime.now(UTC).isoformat()

        if row is None:
            eid = make_evidence_id(url, text_hash)
            self.conn.execute(
                """INSERT INTO issue_evidence
                   (evidence_id, slug, first_seen_run, last_seen_run, seen_count,
                    tier, source_type, source_name, source_handle, canonical_url,
                    title, excerpt, full_text_hash, published_at, fetched_at,
                    language, stance, credibility_score, credibility_basis)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    eid,
                    evidence.slug,
                    current_run_id,
                    current_run_id,
                    evidence.tier,
                    evidence.source_type,
                    evidence.source_name,
                    evidence.source_handle,
                    url,
                    evidence.title,
                    evidence.excerpt[:1000] if evidence.excerpt else "",
                    text_hash,
                    evidence.published_at,
                    now_iso,
                    evidence.language,
                    evidence.stance,
                    evidence.credibility_score,
                    json.dumps(evidence.credibility_basis)
                    if evidence.credibility_basis
                    else None,
                ),
            )
            self.conn.commit()
            final = evidence.model_copy(
                update={
                    "evidence_id": eid,
                    "canonical_url": url,
                    "first_seen_run": current_run_id,
                    "last_seen_run": current_run_id,
                    "fetched_at": now_iso,
                }
            )
            self._embed_evidence(final)
            return True, final
        else:
            self.conn.execute(
                """UPDATE issue_evidence
                   SET last_seen_run = ?, seen_count = seen_count + 1,
                       stance = COALESCE(?, stance),
                       credibility_score = COALESCE(?, credibility_score)
                   WHERE evidence_id = ?""",
                (
                    current_run_id,
                    evidence.stance if evidence.stance != "neutral" else None,
                    evidence.credibility_score,
                    row["evidence_id"],
                ),
            )
            self.conn.commit()
            d = dict(row)
            if d.get("credibility_basis"):
                try:
                    d["credibility_basis"] = json.loads(d["credibility_basis"])
                except Exception:
                    d["credibility_basis"] = None
            final = Evidence(**d)
            return False, final

    def _embed_evidence(self, evidence: Evidence) -> None:
        coll = self._get_chroma_collection()
        if coll is None:
            return
        try:
            doc = f"{evidence.title or ''}\n\n{evidence.excerpt}"[:2000]
            coll.upsert(
                ids=[evidence.evidence_id],
                documents=[doc],
                metadatas=[
                    {
                        "slug": evidence.slug,
                        "tier": str(evidence.tier),
                        "source_type": evidence.source_type,
                        "stance": evidence.stance,
                        "canonical_url": evidence.canonical_url,
                    }
                ],
            )
        except Exception as e:
            logger.warning("ChromaDB embed failed: %s", e)

    def get_evidence_for_slug(self, slug: str) -> list[Evidence]:
        rows = self.conn.execute(
            "SELECT * FROM issue_evidence WHERE slug = ? ORDER BY published_at DESC",
            (slug,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("credibility_basis"):
                try:
                    d["credibility_basis"] = json.loads(d["credibility_basis"])
                except Exception:
                    d["credibility_basis"] = None
            result.append(Evidence(**d))
        return result

    def get_run_count(self, slug: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM issue_runs WHERE slug = ?", (slug,)
        ).fetchone()
        return row[0] if row else 0

    def list_topics(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT slug, title, created_at, last_run_at FROM issue_topics ORDER BY last_run_at DESC NULLS LAST"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_cached_credibility(self, source_handle: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM issue_source_credibility WHERE source_handle = ?",
            (source_handle,),
        ).fetchone()
        if row is None:
            return None
        try:
            dt = datetime.fromisoformat(row["evaluated_at"])
            if datetime.now(UTC) - dt > timedelta(days=30):
                return None
        except Exception:
            pass
        return dict(row)

    def upsert_credibility(
        self,
        source_handle: str,
        source_type: str,
        display_name: str | None,
        score: float,
        rubric_json: str,
        rationale: str,
        evaluated_at: str,
        evaluator_model: str,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO issue_source_credibility
               (source_handle, source_type, display_name, score, rubric_json,
                rationale, evaluated_at, evaluator_model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source_handle,
                source_type,
                display_name,
                score,
                rubric_json,
                rationale,
                evaluated_at,
                evaluator_model,
            ),
        )
        self.conn.commit()

    def semantic_search(
        self, slug: str, query: str, n_results: int = 10
    ) -> list[dict]:
        coll = self._get_chroma_collection()
        if coll is None:
            return []
        try:
            results = coll.query(
                query_texts=[query],
                n_results=n_results,
                where={"slug": slug},
            )
            out = []
            for i, doc_id in enumerate(results["ids"][0]):
                out.append(
                    {
                        "evidence_id": doc_id,
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i],
                    }
                )
            return out
        except Exception as e:
            logger.warning("ChromaDB query failed: %s", e)
            return []
