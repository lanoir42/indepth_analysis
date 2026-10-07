"""Bounded public-access retries for previously unavailable KCIF documents."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx

RETRY_CAP_PER_RUN = 10
INITIAL_WAIT_DAYS = 7
DAY_SECONDS = 86400


def preserve_download(path: Path, external_id: str, destination_dir: Path) -> Path:
    from indepth_analysis.data.kcif_client import file_hash

    digest = file_hash(path)
    destination = destination_dir / f"{external_id}_{digest[:12]}_{path.name}"
    destination_dir.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(path.read_bytes())
    elif file_hash(destination) != digest:
        raise ValueError("Existing document hash conflict")
    return destination


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kcif_download_attempts (
            report_id INTEGER PRIMARY KEY,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_attempt_ts REAL NOT NULL,
            next_retry_ts REAL NOT NULL,
            last_status TEXT NOT NULL,
            available_ts REAL
        )
    """)
    conn.commit()


def run_public_backfill(*, limit: int = 10) -> dict:
    from indepth_analysis.data.kcif_client import KCIFScraper, file_hash
    from indepth_analysis.data.scraper_base import ScraperResult
    from indepth_analysis.db import ReferenceDB
    from indepth_analysis.kcif import store
    from indepth_analysis.kcif.extract_md import extract_report_md
    from indepth_analysis.kcif.paths import (
        DB_PATH,
        KST,
        LOCK_PATH,
        PDF_DIR,
        REFERENCES_DIR,
        REPORTS_OUT_DIR,
    )
    from indepth_analysis.models.reference import DownloadStatus

    if not 1 <= limit <= 117:
        raise ValueError("limit must be between 1 and 117")
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(KST)
        audit = REFERENCES_DIR / ".kcif-backfill" / (
            stamp.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        )
        audit.mkdir(parents=True, mode=0o700)
        original = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        with sqlite3.connect(audit / "before.db") as backup:
            original.backup(backup)
        os.chmod(audit / "before.db", 0o600)
        before = original.execute(
            "SELECT id, download_status, file_name, md_path FROM reports ORDER BY id"
        ).fetchall()
        original.close()
        manifest = {
            "started_at": stamp.isoformat(), "limit": limit,
            "before_reports": before,
            "existing_report_hashes": {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in REPORTS_OUT_DIR.glob("*.md")
            },
            "results": [], "stopped": None,
        }
        manifest_path = audit / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        manifest_path.chmod(0o600)
        db = ReferenceDB(db_path=DB_PATH)
        store.get_conn()
        store.initialize_daily_text_delivery()
        scraper = KCIFScraper()
        server_failures = 0
        transport_failures = 0
        try:
            source = db.get_or_create_source(scraper.source_name, scraper.base_url)
            while len(manifest["results"]) < limit and not manifest["stopped"]:
                report_ids = due_report_ids(
                    db.conn, source.id, stamp.date(),
                    limit=min(RETRY_CAP_PER_RUN, limit - len(manifest["results"])),
                )
                if not report_ids:
                    break
                for report_id in report_ids:
                    report = db.get_report_by_id(report_id)
                    entry = {"report_id": report_id, "extracted": False}
                    try:
                        result = ScraperResult(
                            external_id=report.external_id, title=report.title,
                            url=report.url, published_date=report.published_date,
                        )
                        path = scraper.download_file(
                            result, audit / "downloads" / str(report_id),
                        )
                        server_failures = 0
                        transport_failures = 0
                        if path:
                            path = preserve_download(path, report.external_id, PDF_DIR)
                            state = DownloadStatus.DOWNLOADED
                            db.update_report_download(
                                report_id, status=state, file_name=path.name,
                                file_size_bytes=path.stat().st_size,
                                file_hash=file_hash(path),
                            )
                            record_attempt(db.conn, report_id, state.value)
                            try:
                                entry["extracted"] = bool(
                                    extract_report_md(report, path)
                                )
                            except Exception as extraction_error:
                                entry["extraction_error"] = (
                                    type(extraction_error).__name__
                                )
                        else:
                            state = DownloadStatus.RESTRICTED
                            db.update_report_download(
                                report_id, status=state,
                                error="no file url / restricted",
                            )
                            record_attempt(db.conn, report_id, state.value)
                        entry["status"] = state.value
                    except Exception as error:
                        entry["status"] = "failed"
                        entry["error"] = type(error).__name__
                        db.update_report_download(
                            report_id, status=DownloadStatus.FAILED,
                            error=str(error)[:300],
                        )
                        record_attempt(db.conn, report_id, "failed")
                        if isinstance(error, httpx.HTTPStatusError):
                            transport_failures = 0
                            status_code = error.response.status_code
                            server_failures = (
                                server_failures + 1 if status_code >= 500 else 0
                            )
                            if status_code == 429 or server_failures >= 3:
                                manifest["stopped"] = f"upstream_http_{status_code}"
                        elif isinstance(error, httpx.TransportError):
                            server_failures = 0
                            transport_failures += 1
                            if transport_failures >= 3:
                                manifest["stopped"] = "upstream_transport_errors"
                        else:
                            server_failures = 0
                            transport_failures = 0
                    manifest["results"].append(entry)
                    manifest_path.write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2)
                    )
                    time.sleep(0.7 + random.random() * 0.5)
                    if manifest["stopped"]:
                        break
        finally:
            scraper.close()
            db.close()
        manifest["finished_at"] = datetime.now(KST).isoformat()
        manifest["existing_reports_unchanged"] = all(
            hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
            for path, digest in manifest["existing_report_hashes"].items()
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        return {"manifest": str(manifest_path), "results": manifest["results"],
                "stopped": manifest["stopped"],
                "existing_reports_unchanged": manifest["existing_reports_unchanged"]}


def due_report_ids(
    conn: sqlite3.Connection, source_id: int, target: date,
    *, limit: int = RETRY_CAP_PER_RUN, now: float | None = None,
) -> list[int]:
    ensure_schema(conn)
    current = time.time() if now is None else now
    cutoff = (target - timedelta(days=INITIAL_WAIT_DAYS)).isoformat()
    pending_cutoff = (target - timedelta(days=14)).isoformat()
    rows = conn.execute(
        "SELECT r.id FROM reports r "
        "LEFT JOIN kcif_download_attempts a ON a.report_id = r.id "
        "WHERE r.source_id = ? AND (r.md_path IS NULL OR r.md_path = '') "
        "AND COALESCE(r.published_date, '') <= ? "
        "AND (r.download_status IN ('restricted', 'failed') "
        "OR (r.download_status = 'pending' "
        "AND COALESCE(r.published_date, '') < ?)) "
        "AND (a.next_retry_ts IS NULL OR a.next_retry_ts <= ?) "
        "ORDER BY COALESCE(a.last_attempt_ts, 0), "
        "COALESCE(r.published_date, ''), r.id LIMIT ?",
        (source_id, cutoff, pending_cutoff, current,
         max(0, min(limit, RETRY_CAP_PER_RUN))),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def record_attempt(
    conn: sqlite3.Connection, report_id: int, status: str,
    *, now: float | None = None, retry_after_days: int | None = None,
) -> None:
    ensure_schema(conn)
    current = time.time() if now is None else now
    previous = conn.execute(
        "SELECT attempts FROM kcif_download_attempts WHERE report_id = ?",
        (report_id,),
    ).fetchone()
    attempts = int(previous["attempts"]) + 1 if previous else 1
    delay_days = min(30, INITIAL_WAIT_DAYS * (2 ** min(attempts - 1, 3)))
    if retry_after_days is not None:
        if retry_after_days < 1:
            raise ValueError("retry_after_days must be positive")
        delay_days = retry_after_days
    conn.execute(
        "INSERT INTO kcif_download_attempts "
        "(report_id, attempts, last_attempt_ts, next_retry_ts, last_status, "
        "available_ts) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(report_id) DO UPDATE SET attempts = excluded.attempts, "
        "last_attempt_ts = excluded.last_attempt_ts, "
        "next_retry_ts = excluded.next_retry_ts, "
        "last_status = excluded.last_status, "
        "available_ts = COALESCE(kcif_download_attempts.available_ts, "
        "excluded.available_ts)",
        (report_id, attempts, current, current + delay_days * DAY_SECONDS,
         status, current if status == "downloaded" else None),
    )
    conn.commit()
