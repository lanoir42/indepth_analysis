import copy
import fcntl
import sqlite3

import pytest

from indepth_analysis.kcif import settings, store


@pytest.fixture
def database(monkeypatch, tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE reports (id INTEGER PRIMARY KEY, published_date TEXT);
        CREATE TABLE report_texts (id INTEGER PRIMARY KEY, report_id INTEGER);
        CREATE TABLE kcif_topics (
          id INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT, description TEXT,
          keywords_json TEXT, status TEXT DEFAULT 'active', summary_text TEXT, summary_ts REAL,
          created_ts REAL, archived_ts REAL, last_event_ts REAL, watermark_id INTEGER);
    """)
    monkeypatch.setattr(store, "get_conn", lambda: conn)
    monkeypatch.setattr(settings, "LOCK_PATH", tmp_path / "daily.lock")
    store.create_topic("금리", "기존 설명", ["금리", "rates"], watermark_id=42)
    conn.execute("UPDATE kcif_topics SET summary_text='기존 요약'")
    conn.commit()
    yield conn
    conn.close()


def test_save_changes_the_next_consumer_without_regenerating(database):
    current = settings.snapshot()
    edited = copy.deepcopy(current["topics"])
    edited[0].update(title="금리와 물가", keywords=["inflation", "물가"])
    result = settings.save({"revision": current["revision"], "topics": edited})
    row = store.list_topics(status="active")[0]
    assert row["keywords"] == ["inflation", "물가"]
    assert row["summary_text"] == "기존 요약" and row["watermark_id"] == 42
    assert result["revision"] != current["revision"]


def test_stale_editor_cannot_overwrite_settings(database):
    current = settings.snapshot()
    edited = copy.deepcopy(current["topics"])
    edited[0]["enabled"] = False
    settings.save({"revision": current["revision"], "topics": edited})
    with pytest.raises(settings.SettingsError, match="다른 곳"):
        settings.save({"revision": current["revision"], "topics": current["topics"]})
    assert store.list_topics(status="active") == []


def test_new_topic_uses_bounded_initial_watermark(database):
    database.execute("INSERT INTO reports VALUES (1,'2000-01-01')")
    database.execute("INSERT INTO report_texts VALUES (7,1)")
    database.commit()
    current = settings.snapshot()
    current["topics"].append({"slug": "", "title": "새 토픽", "description": "",
                              "keywords": ["원자재"], "enabled": True})
    settings.save({"revision": current["revision"], "topics": current["topics"]})
    assert store.get_topic("새-토픽")["watermark_id"] == 7


def test_validation_and_omission_do_not_partially_save(database):
    current = settings.snapshot()
    with pytest.raises(settings.SettingsError):
        settings.save({"revision": current["revision"], "topics": []})
    malformed = copy.deepcopy(current["topics"])
    malformed[0]["keywords"] = ["x"]
    with pytest.raises(settings.SettingsError):
        settings.save({"revision": current["revision"], "topics": malformed})
    assert settings.snapshot() == current


def test_save_does_not_change_an_in_progress_regular_run(database):
    current = settings.snapshot()
    with settings.LOCK_PATH.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(settings.SettingsError) as caught:
            settings.save({"revision": current["revision"], "topics": current["topics"]})
        assert caught.value.code == "busy"
    assert settings.snapshot() == current
