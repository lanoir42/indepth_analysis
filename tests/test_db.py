from pathlib import Path

from indepth_analysis.db import ReferenceDB
from indepth_analysis.models.reference import (
    Chunk,
    DownloadStatus,
    ProcessingStatus,
    Report,
)


class TestReferenceDB:
    def _make_db(self, tmp_path: Path) -> ReferenceDB:
        return ReferenceDB(tmp_path / "test.db")

    def test_schema_creation(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        # Accessing conn triggers schema init
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in tables}
        assert "sources" in names
        assert "reports" in names
        assert "chunks" in names
        db.close()

    def test_get_or_create_source(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        s1 = db.get_or_create_source("KCIF", "https://www.kcif.or.kr")
        assert s1.id is not None
        assert s1.name == "KCIF"

        # Second call returns same
        s2 = db.get_or_create_source("KCIF", "https://www.kcif.or.kr")
        assert s2.id == s1.id
        db.close()

    def test_upsert_report(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        source = db.get_or_create_source("TEST", "https://example.com")
        assert source.id is not None

        report = Report(
            source_id=source.id,
            external_id="123",
            title="Test Report",
            url="https://example.com/123",
        )
        r1 = db.upsert_report(report)
        assert r1.id is not None

        # Upsert same external_id returns existing
        report2 = Report(
            source_id=source.id,
            external_id="123",
            title="Test Report Updated",
            url="https://example.com/123",
        )
        r2 = db.upsert_report(report2)
        assert r2.id == r1.id
        db.close()

    def test_update_report_download(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        source = db.get_or_create_source("TEST", "https://example.com")
        assert source.id is not None

        report = Report(
            source_id=source.id,
            external_id="456",
            title="Download Test",
            url="https://example.com/456",
        )
        report = db.upsert_report(report)
        assert report.id is not None

        db.update_report_download(
            report.id,
            status=DownloadStatus.DOWNLOADED,
            file_name="test.pdf",
            file_size_bytes=1024,
            file_hash="abc123",
        )

        reports = db.get_reports(download_status=DownloadStatus.DOWNLOADED)
        assert len(reports) == 1
        assert reports[0].file_name == "test.pdf"
        assert reports[0].file_size_bytes == 1024
        db.close()

    def test_update_report_processing(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        source = db.get_or_create_source("TEST", "https://example.com")
        assert source.id is not None

        report = Report(
            source_id=source.id,
            external_id="789",
            title="Process Test",
            url="https://example.com/789",
        )
        report = db.upsert_report(report)
        assert report.id is not None

        db.update_report_processing(
            report.id,
            status=ProcessingStatus.EMBEDDED,
            page_count=10,
            extraction_method="pymupdf",
        )

        reports = db.get_reports(processing_status=ProcessingStatus.EMBEDDED)
        assert len(reports) == 1
        assert reports[0].page_count == 10
        db.close()

    def test_insert_and_get_chunks(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        source = db.get_or_create_source("TEST", "https://example.com")
        assert source.id is not None

        report = Report(
            source_id=source.id,
            external_id="chunk_test",
            title="Chunk Test",
            url="https://example.com/ct",
        )
        report = db.upsert_report(report)
        assert report.id is not None

        chunks = [
            Chunk(
                report_id=report.id,
                chunk_index=0,
                content="First chunk",
                page_start=1,
                page_end=1,
                token_count=5,
            ),
            Chunk(
                report_id=report.id,
                chunk_index=1,
                content="Second chunk",
                page_start=2,
                page_end=3,
                token_count=6,
                embedding=b"\x00" * 16,
                embedding_model="test-model",
            ),
        ]
        db.insert_chunks(chunks)

        retrieved = db.get_chunks(report_id=report.id)
        assert len(retrieved) == 2
        assert retrieved[0].content == "First chunk"
        assert retrieved[1].content == "Second chunk"
        db.close()

    def test_get_all_embedded_chunks(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        source = db.get_or_create_source("TEST", "https://example.com")
        assert source.id is not None

        report = Report(
            source_id=source.id,
            external_id="emb_test",
            title="Embedding Test",
            url="https://example.com/emb",
        )
        report = db.upsert_report(report)
        assert report.id is not None

        emb_bytes = b"\x00" * 16
        chunks = [
            Chunk(
                report_id=report.id,
                chunk_index=0,
                content="With embedding",
                embedding=emb_bytes,
                embedding_model="test",
            ),
            Chunk(
                report_id=report.id,
                chunk_index=1,
                content="Without embedding",
            ),
        ]
        db.insert_chunks(chunks)

        embedded = db.get_all_embedded_chunks()
        assert len(embedded) == 1
        assert embedded[0][0].content == "With embedding"
        assert embedded[0][1] == emb_bytes
        db.close()

    def test_status_summary(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        source = db.get_or_create_source("TEST", "https://example.com")
        assert source.id is not None

        for i in range(3):
            db.upsert_report(
                Report(
                    source_id=source.id,
                    external_id=str(i),
                    title=f"Report {i}",
                    url=f"https://example.com/{i}",
                )
            )

        summary = db.get_status_summary()
        assert summary["sources"] == 1
        assert summary["reports"] == 3
        assert summary["download_status"]["pending"] == 3
        db.close()
