"""Tests for the read-only optionsdeck macro DB adapter.

All tests run against a miniature fixture DB that reproduces the relevant part
of the upstream schema -- the real `~/.optionsdeck-gb/data/macro.db` is never
touched here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from indepth_analysis.data import optionsdeck_series as ods
from indepth_analysis.data.optionsdeck_series import (
    OptionsdeckSeriesClient,
    OptionsdeckSeriesError,
    SnapshotError,
)

SCHEMA = """
CREATE TABLE macro_series (
    series_id TEXT NOT NULL,
    date TEXT NOT NULL,
    value REAL,
    source TEXT NOT NULL,
    fetched_ts INTEGER NOT NULL,
    first_seen_ts INTEGER,
    forecast_value REAL,
    publish_date TEXT,
    provenance TEXT,
    PRIMARY KEY (series_id, date)
);
CREATE TABLE macro_calendar_history (
    series_id TEXT NOT NULL,
    release_date TEXT NOT NULL,
    event_title TEXT,
    forecast_display TEXT,
    forecast_value REAL,
    previous_display TEXT,
    previous_value REAL,
    actual_display TEXT,
    actual_value REAL,
    impact TEXT,
    comparable INTEGER DEFAULT 0,
    source TEXT NOT NULL,
    first_seen_ts INTEGER NOT NULL,
    PRIMARY KEY (series_id, release_date)
);
CREATE TABLE macro_calendar_events (
    event_key TEXT PRIMARY KEY,
    title TEXT,
    country TEXT,
    release_at TEXT,
    impact TEXT,
    forecast_display TEXT,
    previous_display TEXT,
    actual_display TEXT,
    first_seen_ts INTEGER
);
CREATE TABLE private_secrets (id TEXT PRIMARY KEY, payload TEXT);
"""

SERIES_ROWS = [
    # EA HICP YoY, monthly DBnomics period labels ('YYYY-MM')
    ("M.RCH_A.CP00.EA", "2025-10", 2.1, "dbnomics", 1785275213922),
    ("M.RCH_A.CP00.EA", "2025-11", 2.1, "dbnomics", 1785275213922),
    ("M.RCH_A.CP00.EA", "2025-12", 1.9, "dbnomics", 1785275213922),
    # Daily FRED series, with one NULL (market holiday)
    ("VIXCLS", "2026-07-24", 15.4, "fred", 1785459305691),
    ("VIXCLS", "2026-07-27", None, "fred", 1785459305691),
    ("VIXCLS", "2026-07-28", 16.1, "fred", 1785459305691),
]

CALENDAR_ROWS = [
    (
        "EU.HICP_YOY",
        "2026-04-30",
        "CPI y/y",
        "2.3",
        2.3,
        "2.6",
        2.6,
        "1.9",
        1.9,
        "High",
        1,
        "jblanked",
        1785275711649,
    ),
    (
        "EU.HICP_YOY",
        "2026-07-31",
        "CPI Flash Estimate y/y",
        "2.9%",
        2.9,
        "2.8%",
        2.8,
        None,
        None,
        "Medium",
        1,
        "faireconomy",
        1785218648427,
    ),
    (
        "EU.UNRATE",
        "2026-07-30",
        "Unemployment Rate",
        "6.3%",
        6.3,
        "6.3%",
        6.3,
        None,
        None,
        "Low",
        1,
        "faireconomy",
        1785218648427,
    ),
    (
        "US.NFP",
        "2026-05-08",
        "Non-Farm Employment Change",
        "130K",
        130.0,
        "114K",
        114.0,
        "125K",
        125.0,
        "High",
        0,
        "jblanked",
        1785275711649,
    ),
]


def _build_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO macro_series "
        "(series_id, date, value, source, fetched_ts) VALUES (?, ?, ?, ?, ?)",
        SERIES_ROWS,
    )
    conn.executemany(
        "INSERT INTO macro_calendar_history VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        CALENDAR_ROWS,
    )
    conn.execute(
        "INSERT INTO macro_calendar_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "abc123",
            "Chicago PMI",
            "USD",
            "2026-07-31T09:45:00-04:00",
            "Low",
            "55.9",
            "56.7",
            None,
            1785369538120,
        ),
    )
    conn.execute("INSERT INTO private_secrets VALUES ('k', 'v')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def _clear_snapshot_cache():
    ods._SNAPSHOT_CACHE.clear()
    yield
    ods._SNAPSHOT_CACHE.clear()


@pytest.fixture
def macro_db(tmp_path: Path) -> Path:
    return _build_db(tmp_path / "macro.db")


@pytest.fixture
def client(macro_db: Path):
    c = OptionsdeckSeriesClient(macro_db)
    yield c
    c.close()


# --- availability -----------------------------------------------------------


def test_available_reports_schema_and_freshness(client: OptionsdeckSeriesClient):
    info = client.available()
    assert info.available is True
    assert bool(info) is True
    assert info.reason is None
    assert info.missing == ()
    assert info.series_count == 2
    # only full ISO dates count as observation dates (monthly labels excluded)
    assert info.latest_observation_date == "2026-07-28"
    assert info.latest_calendar_release == "2026-07-31"
    assert info.fetched_at is not None and info.fetched_at.endswith("Z")


def test_available_missing_file_degrades(tmp_path: Path):
    info = OptionsdeckSeriesClient(tmp_path / "nope.db").available()
    assert info.available is False
    assert "not found" in (info.reason or "")
    assert info.latest_observation_date is None


def test_available_missing_column_degrades(tmp_path: Path):
    path = _build_db(tmp_path / "macro.db")
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE macro_calendar_history DROP COLUMN actual_value")
    conn.execute("DROP TABLE macro_calendar_events")
    conn.commit()
    conn.close()

    info = OptionsdeckSeriesClient(path).available()
    assert info.available is False
    assert "macro_calendar_history.actual_value" in info.missing
    assert "macro_calendar_events" in info.missing


def test_available_ignores_user_version(client: OptionsdeckSeriesClient):
    """Source schema is idempotent and leaves user_version at 0 -- not a fault."""
    assert client.available().available is True
    conn = client._connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


# --- series queries ---------------------------------------------------------


def test_list_series(client: OptionsdeckSeriesClient):
    series = {s.series_id: s for s in client.list_series()}
    assert set(series) == {"M.RCH_A.CP00.EA", "VIXCLS"}
    hicp = series["M.RCH_A.CP00.EA"]
    assert hicp.source == "dbnomics"
    assert hicp.n_obs == 3
    assert (hicp.first_date, hicp.last_date) == ("2025-10", "2025-12")
    assert series["VIXCLS"].n_obs == 3  # NULL rows still count as observations


def test_get_series_ascending_and_drops_nulls(client: OptionsdeckSeriesClient):
    obs = client.get_series("VIXCLS")
    assert [o.date for o in obs] == ["2026-07-24", "2026-07-28"]
    assert [o.value for o in obs] == [15.4, 16.1]

    with_nulls = client.get_series("VIXCLS", include_null=True)
    assert len(with_nulls) == 3
    assert with_nulls[1].value is None


def test_get_series_date_range_is_inclusive(client: OptionsdeckSeriesClient):
    obs = client.get_series("M.RCH_A.CP00.EA", start="2025-11", end="2025-12")
    assert [(o.date, o.value) for o in obs] == [("2025-11", 2.1), ("2025-12", 1.9)]
    assert client.get_series("M.RCH_A.CP00.EA", start="2026-01") == []
    assert client.get_series("NO.SUCH.SERIES") == []


# --- calendar history -------------------------------------------------------


def test_get_calendar_history_filters_and_passthrough(client: OptionsdeckSeriesClient):
    rows = client.get_calendar_history(country="EU")
    assert [r.series_id for r in rows] == ["EU.HICP_YOY", "EU.UNRATE", "EU.HICP_YOY"]
    assert all(r.country == "EU" for r in rows)
    # release_date ascending
    assert [r.release_date for r in rows] == ["2026-04-30", "2026-07-30", "2026-07-31"]

    hicp = client.get_calendar_history(series_id="EU.HICP_YOY", end="2026-06-30")
    assert len(hicp) == 1
    row = hicp[0]
    # REAL columns exposed verbatim, never re-parsed from the display strings
    assert (row.forecast_value, row.previous_value, row.actual_value) == (2.3, 2.6, 1.9)
    assert row.forecast_display == "2.3"
    assert row.impact == "High"
    assert row.comparable is True
    assert row.source == "jblanked"

    nfp = client.get_calendar_history(country="us")
    assert len(nfp) == 1 and nfp[0].comparable is False
    assert client.get_calendar_history(start="2026-08-01") == []


# --- snapshot behaviour -----------------------------------------------------


def test_source_db_is_never_written(macro_db: Path):
    before = macro_db.stat()
    client = OptionsdeckSeriesClient(macro_db)
    client.available()
    client.list_series()
    client.get_series("VIXCLS")
    client.get_calendar_history()
    after = macro_db.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    # no WAL/SHM sidecars created by us
    assert not (macro_db.parent / f"{macro_db.name}-wal").exists()
    assert not (macro_db.parent / f"{macro_db.name}-shm").exists()
    # queries run against a copy, not the live file
    assert client.snapshot_path is not None
    assert client.snapshot_path != macro_db
    client.close()


def test_snapshot_is_cached_per_source_state(macro_db: Path, monkeypatch):
    copies: list[tuple[Path, Path]] = []
    real_copyfile = ods.shutil.copyfile

    def counting_copyfile(src, dst, **kwargs):
        copies.append((Path(src), Path(dst)))
        return real_copyfile(src, dst, **kwargs)

    monkeypatch.setattr(ods.shutil, "copyfile", counting_copyfile)

    first = OptionsdeckSeriesClient(macro_db)
    first.available()
    second = OptionsdeckSeriesClient(macro_db)
    second.list_series()
    assert len(copies) == 1
    assert first.snapshot_path == second.snapshot_path
    first.close()
    second.close()


def test_torn_copy_retries_then_succeeds(macro_db: Path, monkeypatch):
    """Header change counter moving during the copy forces a re-copy."""
    counters = iter([(1, 10), (2, 10), (2, 10), (2, 10)])
    monkeypatch.setattr(ods, "_read_change_counter", lambda path: next(counters))

    client = OptionsdeckSeriesClient(macro_db)
    assert client.available().available is True  # second attempt was clean
    assert next(counters, "exhausted") == "exhausted"
    client.close()


def test_torn_copy_exhausts_retries(macro_db: Path, monkeypatch):
    seq = iter(range(100))
    monkeypatch.setattr(ods, "_read_change_counter", lambda path: (next(seq), 10))

    client = OptionsdeckSeriesClient(macro_db)
    with pytest.raises(SnapshotError, match="consistent snapshot"):
        client.list_series()
    # available() converts the failure into a graceful "unavailable"
    info = client.available()
    assert info.available is False
    assert "consistent snapshot" in (info.reason or "")


def test_read_change_counter_matches_header(macro_db: Path):
    counter, size = ods._read_change_counter(macro_db)
    with open(macro_db, "rb") as fh:
        header = fh.read(28)
    assert counter == int.from_bytes(header[24:28], "big")
    assert size == macro_db.stat().st_size


def test_read_change_counter_rejects_stub_file(tmp_path: Path):
    stub = tmp_path / "tiny.db"
    stub.write_bytes(b"not a db")
    with pytest.raises(SnapshotError, match="too small"):
        ods._read_change_counter(stub)


# --- configuration ----------------------------------------------------------


def test_env_override_and_ctor_precedence(macro_db: Path, tmp_path, monkeypatch):
    monkeypatch.setenv(ods.ENV_DB_PATH, str(macro_db))
    assert OptionsdeckSeriesClient().db_path == macro_db

    other = tmp_path / "explicit.db"
    assert OptionsdeckSeriesClient(other).db_path == other  # ctor wins over env

    monkeypatch.delenv(ods.ENV_DB_PATH)
    assert OptionsdeckSeriesClient().db_path == ods.DEFAULT_DB_PATH


def test_queries_raise_when_db_missing(tmp_path: Path):
    client = OptionsdeckSeriesClient(tmp_path / "nope.db")
    with pytest.raises(OptionsdeckSeriesError, match="not found"):
        client.list_series()


def test_allowed_tables_are_the_only_ones_queried():
    source = Path(ods.__file__).read_text()
    body = source.split('"""', 2)[2]  # drop the module docstring
    forbidden = (
        "private_secrets",
        "macro_brief",
        "fed_documents",
        "thesis_scenarios",
        "event_specs",
        "macro_calendar\n",  # the live `macro_calendar` table, not *_history
    )
    for table in forbidden:
        assert table not in body
    assert "import options_analyzer" not in source
    assert "from options_analyzer" not in source
    for table in ods.ALLOWED_TABLES:
        assert table in body
