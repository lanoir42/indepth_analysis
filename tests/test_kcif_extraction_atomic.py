import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from indepth_analysis.kcif import extract_md, store


@pytest.fixture
def extraction(monkeypatch, tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE reports (id INTEGER PRIMARY KEY, source_id INTEGER, "
                 "download_status TEXT, md_path TEXT, published_date TEXT)")
    conn.execute("CREATE TABLE report_texts (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "report_id INTEGER UNIQUE, text TEXT, char_count INTEGER, created_ts REAL)")
    conn.execute("INSERT INTO reports VALUES (1, 1, 'downloaded', NULL, '2026-09-01')")
    conn.commit()
    monkeypatch.setattr(store, "get_conn", lambda: conn)
    monkeypatch.setattr(extract_md, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(extract_md, "MD_DIR", tmp_path / "md")
    monkeypatch.setattr(extract_md, "_extract_images", lambda *args: ["![그림 1](img/test.png)"])
    page = Mock()
    page.get_text.return_value = "합성 본문"
    doc = Mock()
    doc.__iter__ = Mock(side_effect=lambda: iter([page]))
    monkeypatch.setattr(extract_md.fitz, "open", lambda *args: doc)
    report = SimpleNamespace(id=1, source_id=1, title="합성 자료", category="", author="",
                             published_date="2026-09-01", url="https://example.invalid",
                             external_id="synthetic", file_name="synthetic.pdf")
    pdf = tmp_path / report.file_name
    pdf.write_bytes(b"synthetic PDF fixture")
    yield conn, page, report, pdf
    conn.close()


def test_normal_extraction_commits_path_and_body_together(extraction):
    conn, page, report, pdf = extraction
    path = extract_md.extract_report_md(report, pdf)
    assert path and Path(path).exists()
    assert conn.execute("SELECT md_path FROM reports").fetchone()[0]
    assert "합성 본문" in conn.execute("SELECT text FROM report_texts").fetchone()[0]


def test_image_only_document_is_not_extracted_or_indexed(extraction):
    conn, page, report, pdf = extraction
    page.get_text.return_value = "   "
    assert extract_md.extract_report_md(report, pdf) is None
    assert pdf.read_bytes() == b"synthetic PDF fixture"
    assert conn.execute("SELECT md_path FROM reports").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM report_texts").fetchone()[0] == 0
    assert not extract_md.md_path_for(report).exists()


@pytest.mark.parametrize("failure_stage", ["text", "path"])
def test_failed_atomic_update_restores_old_path_and_text(extraction, failure_stage):
    conn, page, report, pdf = extraction
    old_id = store.upsert_report_text(1, "기존 본문", md_path="original.md")
    trigger = ("BEFORE INSERT ON report_texts" if failure_stage == "text"
               else "BEFORE UPDATE ON reports")
    conn.execute(f"CREATE TRIGGER fail_write {trigger} BEGIN "
                 "SELECT RAISE(ABORT, 'synthetic failure'); END")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
        extract_md.extract_report_md(report, pdf)
    assert conn.execute("SELECT md_path FROM reports").fetchone()[0] == "original.md"
    assert tuple(conn.execute("SELECT id, text FROM report_texts").fetchone()) == (old_id, "기존 본문")


@pytest.mark.parametrize("body", [None, "", "  "])
def test_backfill_repairs_path_without_usable_text(extraction, monkeypatch, body):
    conn, page, report, pdf = extraction
    conn.execute("UPDATE reports SET md_path = 'orphan.md'")
    if body is not None:
        store.upsert_report_text(1, body)
    conn.commit()
    from indepth_analysis.kcif import paths
    monkeypatch.setattr(paths, "PDF_DIR", pdf.parent)
    db = SimpleNamespace(get_report_by_id=lambda report_id: report)
    outcome = extract_md.backfill_all(db, 1)
    assert outcome["ok"] == 1
    assert "합성 본문" in conn.execute("SELECT text FROM report_texts").fetchone()[0]


def test_complete_existing_body_is_not_reextracted(extraction, monkeypatch):
    conn, page, report, pdf = extraction
    store.upsert_report_text(1, "보존 본문", md_path="original.md")
    db = Mock()
    outcome = extract_md.backfill_all(db, 1)
    assert outcome["total"] == 0
    db.get_report_by_id.assert_not_called()
    assert conn.execute("SELECT text FROM report_texts").fetchone()[0] == "보존 본문"


def test_backfill_repairs_explicit_null_text(extraction, monkeypatch):
    conn, page, report, pdf = extraction
    conn.execute("UPDATE reports SET md_path = 'orphan.md'")
    conn.execute("INSERT INTO report_texts (report_id, text) VALUES (1, NULL)")
    conn.commit()
    from indepth_analysis.kcif import paths
    monkeypatch.setattr(paths, "PDF_DIR", pdf.parent)
    db = SimpleNamespace(get_report_by_id=lambda report_id: report)
    assert extract_md.backfill_all(db, 1)["ok"] == 1


def test_failed_markdown_write_does_not_update_database(extraction, monkeypatch):
    conn, page, report, pdf = extraction
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("disk unavailable")))
    with pytest.raises(OSError, match="disk unavailable"):
        extract_md.extract_report_md(report, pdf)
    assert conn.execute("SELECT md_path FROM reports").fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM report_texts").fetchone()[0] == 0
