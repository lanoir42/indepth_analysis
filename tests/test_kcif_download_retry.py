import sqlite3
from datetime import date

import pytest

from indepth_analysis.kcif import download_retry as retry


@pytest.fixture
def conn():
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.execute("""
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY, source_id INTEGER, published_date TEXT,
            download_status TEXT, md_path TEXT
        )
    """)
    yield database
    database.close()


def add_report(conn, report_id, day="2026-01-05", state="restricted"):
    conn.execute("INSERT INTO reports VALUES (?, 1, ?, ?, NULL)",
                 (report_id, day, state))
    conn.commit()


def test_cap_and_oldest_first(conn):
    for report_id in range(1, 15):
        add_report(conn, report_id)
    assert retry.due_report_ids(conn, 1, date(2026, 10, 7), limit=100) == list(
        range(1, 11)
    )


def test_new_restricted_waits_seven_days(conn):
    add_report(conn, 1, "2026-10-06")
    assert retry.due_report_ids(conn, 1, date(2026, 10, 7)) == []
    assert retry.due_report_ids(conn, 1, date(2026, 10, 13)) == [1]


def test_old_failed_and_pending_are_not_starved(conn):
    add_report(conn, 1, state="failed")
    add_report(conn, 2, state="pending")
    add_report(conn, 3, "2026-10-01", "pending")
    assert retry.due_report_ids(conn, 1, date(2026, 10, 7)) == [1, 2]


def test_backoff_and_untried_first(conn):
    add_report(conn, 1)
    add_report(conn, 2)
    for attempt, delay in enumerate((7, 14, 28, 30, 30), start=1):
        retry.record_attempt(conn, 1, "restricted", now=1000)
        row = conn.execute("SELECT * FROM kcif_download_attempts").fetchone()
        assert row["attempts"] == attempt
        assert row["next_retry_ts"] == 1000 + delay * retry.DAY_SECONDS
    assert retry.due_report_ids(conn, 1, date(2026, 10, 7), now=1001) == [2]
    assert retry.due_report_ids(conn, 1, date(2026, 10, 7), now=9e9) == [2, 1]


def test_acquisition_time_preserves_publication_date(conn):
    add_report(conn, 1)
    retry.record_attempt(conn, 1, "downloaded", now=1000)
    retry.record_attempt(conn, 1, "downloaded", now=2000)
    assert conn.execute(
        "SELECT available_ts FROM kcif_download_attempts"
    ).fetchone()[0] == 1000
    assert conn.execute("SELECT published_date FROM reports").fetchone()[0] == (
        "2026-01-05"
    )


@pytest.mark.parametrize("limit", [0, -1, 118])
def test_manual_limit_rejected_without_side_effects(limit):
    with pytest.raises(ValueError, match="limit"):
        retry.run_public_backfill(limit=limit)


def test_ingest_propagates_restricted_and_retryable_failure(tmp_path, monkeypatch):
    from indepth_analysis import db as db_module
    from indepth_analysis.data import kcif_client
    from indepth_analysis.kcif import extract_md, report, store
    from indepth_analysis.models.reference import Report

    database = db_module.ReferenceDB(db_path=tmp_path / "test.db")
    store.migrate(database.conn)
    source = database.get_or_create_source("KCIF", "https://www.kcif.or.kr")
    for report_id in (1, 2):
        database.upsert_report(Report(
            source_id=source.id, external_id=str(report_id), title="Test",
            published_date="2026-10-06", url="https://www.kcif.or.kr/view",
        ))
    monkeypatch.setattr(db_module, "ReferenceDB", lambda **kwargs: database)
    monkeypatch.setattr(database, "close", lambda: None)
    monkeypatch.setattr(report.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(kcif_client.KCIFScraper, "scrape_listing", lambda *a, **k: [])

    def download(self, result, destination):
        if result.external_id == "1":
            return None
        raise ValueError("KCIF download returned HTML instead of a document")

    monkeypatch.setattr(kcif_client.KCIFScraper, "download_file", download)
    monkeypatch.setattr(extract_md, "backfill_all", lambda *a: {"ok": 0, "fail": 0})
    status = {}
    report._crawl_and_ingest(status, date(2026, 10, 7))
    rows = database.conn.execute(
        "SELECT download_status FROM reports ORDER BY id"
    ).fetchall()
    assert [row[0] for row in rows] == ["restricted", "failed"]
    assert database.conn.execute(
        "SELECT COUNT(*) FROM kcif_download_attempts"
    ).fetchone()[0] == 2
    assert "접근 제한/주소 미확인 1건" in status["download"]
    assert "실패 1건" in status["download"]
    report._crawl_and_ingest({}, date(2026, 10, 7))
    assert database.conn.execute(
        "SELECT MAX(attempts) FROM kcif_download_attempts"
    ).fetchone()[0] == 1
    current = report.time.time()
    monkeypatch.setattr(report.time, "time", lambda: current + 86401)
    report._crawl_and_ingest({}, date(2026, 10, 8))
    assert database.conn.execute(
        "SELECT attempts FROM kcif_download_attempts WHERE report_id = 2"
    ).fetchone()[0] == 2
    database.conn.close()


@pytest.mark.parametrize("http_status,expected,stopped", [
    (200, 10, None), (429, 1, "upstream_http_429"),
    (503, 3, "upstream_http_503"),
    (-1, 3, "upstream_transport_errors"), (201, 10, None),
])
def test_manual_backup_bounds_stop_and_no_report_rewrite(
    tmp_path, monkeypatch, http_status, expected, stopped,
):
    import json
    from pathlib import Path

    import httpx

    from indepth_analysis.data.kcif_client import KCIFScraper
    from indepth_analysis.db import ReferenceDB
    from indepth_analysis.kcif import extract_md, paths, store
    from indepth_analysis.models.reference import Report

    references = tmp_path / "references"
    references.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    original_report = reports / "2026-01-05.md"
    original_report.write_text("Original report stays unchanged")
    database_path = references / "test.db"
    database = ReferenceDB(db_path=database_path)
    store.migrate(database.conn)
    source = database.get_or_create_source("KCIF", "https://www.kcif.or.kr")
    for report_id in range(15):
        database.upsert_report(Report(
            source_id=source.id, external_id=str(report_id), title="Old report",
            published_date="2026-01-05", url="https://www.kcif.or.kr/view",
            download_status="restricted",
        ))
    database.close()
    for name, value in {
        "DB_PATH": database_path, "REFERENCES_DIR": references,
        "LOCK_PATH": references / "lock", "PDF_DIR": references / "KCIF",
        "REPORTS_OUT_DIR": reports,
    }.items():
        monkeypatch.setattr(paths, name, value)
    monkeypatch.setattr(store, "DB_PATH", database_path)
    monkeypatch.setattr(store, "_conn", None)
    monkeypatch.setattr(retry.time, "sleep", lambda seconds: None)
    def extract(*args):
        if http_status == 201:
            raise RuntimeError("Extraction failed after successful download")
        return "ok"

    monkeypatch.setattr(extract_md, "extract_report_md", extract)

    def download(self, result, destination):
        assert result.file_url is None
        if http_status == -1:
            raise httpx.ConnectError("Offline")
        if http_status not in (200, 201):
            response = httpx.Response(
                http_status, request=httpx.Request("GET", result.url),
            )
            response.raise_for_status()
        destination.mkdir(parents=True)
        document = destination / "report.pdf"
        document.write_bytes(b"%PDF-1.7" + b"test document" * 20)
        return document

    monkeypatch.setattr(KCIFScraper, "download_file", download)
    try:
        outcome = retry.run_public_backfill(limit=10)
        assert len(outcome["results"]) == expected
        assert outcome["stopped"] == stopped
        assert outcome["existing_reports_unchanged"] is True
        if http_status == 201:
            assert all(row["status"] == "downloaded" for row in outcome["results"])
            assert all(row["extracted"] is False for row in outcome["results"])
        manifest_path = Path(outcome["manifest"])
        assert (manifest_path.stat().st_mode & 0o777) == 0o600
        backup = manifest_path.parent / "before.db"
        assert (backup.stat().st_mode & 0o777) == 0o600
        with sqlite3.connect(backup) as before:
            assert before.execute(
                "SELECT COUNT(*) FROM reports WHERE download_status='restricted'"
            ).fetchone()[0] == 15
        assert json.loads(manifest_path.read_text())["finished_at"]
    finally:
        if store._conn is not None:
            store._conn.close()
            store._conn = None


def test_retry_preserves_existing_same_filename(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    incoming = staging / "report.pdf"
    incoming.write_bytes(b"new document")
    destination = tmp_path / "archive"
    destination.mkdir()
    existing = destination / "report.pdf"
    existing.write_bytes(b"existing document")
    result = retry.preserve_download(incoming, "123", destination)
    assert result.name.startswith("123_")
    assert result.read_bytes() == b"new document"
    assert existing.read_bytes() == b"existing document"


def test_manual_backfill_obeys_daily_lock(tmp_path, monkeypatch):
    import fcntl

    from indepth_analysis.kcif import paths

    lock_path = tmp_path / "daily.lock"
    monkeypatch.setattr(paths, "LOCK_PATH", lock_path)
    monkeypatch.setattr(paths, "REFERENCES_DIR", tmp_path / "references")
    with lock_path.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            retry.run_public_backfill(limit=10)
    assert not (tmp_path / "references").exists()
