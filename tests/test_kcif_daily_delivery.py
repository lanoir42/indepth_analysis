import sqlite3

import pytest

from indepth_analysis.kcif import report, store


@pytest.fixture
def delivery(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE reports (id INTEGER, title TEXT, category TEXT, md_path TEXT, published_date TEXT)")
    conn.execute("CREATE TABLE report_texts (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER, text TEXT)")
    monkeypatch.setattr(store, "get_conn", lambda: conn)
    yield conn
    conn.close()


def add_text(conn, report_id, published="2026-09-01"):
    conn.execute("INSERT INTO reports VALUES (?, '過去資料', '미국', 'references/test.md', ?)", (report_id, published))
    return conn.execute("INSERT INTO report_texts (report_id, text) VALUES (?, '■ 주요 뉴스: 과거 사건')", (report_id,)).lastrowid


def test_baseline_and_late_delivery_across_days(delivery):
    add_text(delivery, 1)
    store.initialize_daily_text_delivery()
    late_id = add_text(delivery, 2)
    store.initialize_daily_text_delivery()
    rows = store.pending_daily_texts("2026-10-07", "2026-10-07")
    assert [row["text_id"] for row in rows] == [late_id]
    assert store.pending_daily_texts("2026-10-12", "2026-10-10") == rows
    store.mark_daily_texts("2026-10-12", [], [late_id])
    assert store.pending_daily_texts("2026-10-12", "2026-10-10") == rows
    assert store.pending_daily_texts("2026-10-13", "2026-10-13") == []


def test_same_day_addition_and_regular_delivery(delivery):
    store.initialize_daily_text_delivery()
    first = add_text(delivery, 1)
    store.mark_daily_texts("2026-10-07", [], [first])
    add_text(delivery, 2)
    assert len(store.pending_daily_texts("2026-10-07", "2026-10-07")) == 2
    store.mark_daily_texts("2026-10-07", [2], [])
    assert store.pending_daily_texts("2026-10-08", "2026-10-08") == []


def test_cap_keeps_undelivered_rows(delivery):
    store.initialize_daily_text_delivery()
    for report_id in range(4):
        add_text(delivery, report_id)
    rows = store.pending_daily_texts("2026-10-07", "2026-10-07", cap=2)
    store.mark_daily_texts("2026-10-07", [], [row["text_id"] for row in rows])
    assert len(store.pending_daily_texts("2026-10-08", "2026-10-08")) == 2


def test_today_and_future_not_backfill(delivery):
    store.initialize_daily_text_delivery()
    add_text(delivery, 1, "2026-10-07")
    add_text(delivery, 2, "2026-10-08")
    assert store.pending_daily_texts("2026-10-07", "2026-10-07") == []


def test_late_report_states_original_date(delivery, monkeypatch):
    store.initialize_daily_text_delivery()
    add_text(delivery, 1)
    monkeypatch.setattr(store, "list_topics", lambda **kwargs: [])
    rows = store.pending_daily_texts("2026-10-07", "2026-10-07")
    md = report.render_daily("2026-10-07", {}, {}, [], late_reports=rows)
    assert "## 뒤늦게 확보된 KCIF 원문 (1건)" in md
    assert "원발행일: 2026-09-01" in md
    assert "오늘 발생한 사건을 뜻하지 않습니다" in md


@pytest.mark.parametrize("write_fails", [False, True])
def test_backfill_prevents_holiday_skip_and_only_consumed_after_write(delivery, monkeypatch, tmp_path, write_fails):
    monkeypatch.setattr(report, "LOCK_PATH", tmp_path / "lock")
    monkeypatch.setattr(report, "REPORTS_OUT_DIR", tmp_path / "reports")
    monkeypatch.setattr(report, "SKIP_MARKER_DIR", tmp_path / "reports" / ".skipped")
    monkeypatch.setattr(store, "list_topics", lambda **kwargs: [])
    monkeypatch.setattr(report.topics_mod, "update_all", lambda: [])
    monkeypatch.setattr(report.topics_mod, "write_topic_dumps", lambda active: {})
    monkeypatch.setattr(report, "collect_new_reports", lambda day: ([], ""))
    monkeypatch.setattr(report, "_self_heal_periodics", lambda *args: [])

    def ingest(status, target):
        status["_new_count"] = 0
        add_text(delivery, 1)

    monkeypatch.setattr(report, "_crawl_and_ingest", ingest)
    if write_fails:
        def fail_write(*args, **kwargs):
            raise OSError("disk unavailable")
        monkeypatch.setattr(report.Path, "write_text", fail_write)
        with pytest.raises(OSError):
            report.run_daily("2026-10-07")
        assert len(store.pending_daily_texts("2026-10-08", "2026-10-08")) == 1
    else:
        result = report.run_daily("2026-10-07")
        assert "skipped" not in result
        assert store.pending_daily_texts("2026-10-08", "2026-10-08") == []
