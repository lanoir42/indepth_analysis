"""Read-only adapter over the optionsdeck macro SQLite database.

The source database (`~/.optionsdeck-gb/data/macro.db`) is owned by a separate
project and written by a launchd collector roughly twice a day.  It runs in WAL
mode with a live writer attached, which rules out both naive read strategies:

* ``file:...?mode=ro`` fails with ``SQLITE_CANTOPEN`` (WAL needs write access to
  the ``-shm``/``-wal`` sidecars).
* opening the live file with ``immutable=1`` silently reads a file that may be
  mutated underneath us -- corrupt pages / phantom rows during a writer commit.

So this adapter takes a **byte snapshot** of the database into a process-scoped
temporary directory and opens the *copy* with ``immutable=1``.  A torn copy is
detected by comparing the SQLite header change counter (file offset 24, 4 bytes
big-endian) plus the file size immediately before and after the copy; on a
mismatch the copy is retried up to :data:`MAX_SNAPSHOT_RETRIES` times before
raising :class:`SnapshotError`.

Invariants (deliberate, do not relax):

* the source file is only ever opened ``rb`` -- no writes, no locks, no sidecar
  files created;
* only the tables in :data:`ALLOWED_TABLES` are queried (the rest of macro.db is
  private to the owning project);
* no ``options_analyzer`` import -- this module talks to the file, not the code;
* ``PRAGMA user_version`` is **not** checked: the source schema is created
  idempotently and leaves user_version at 0, so it carries no version signal.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_DB_PATH = "OPTIONSDECK_MACRO_DB"
DEFAULT_DB_PATH = Path.home() / ".optionsdeck-gb" / "data" / "macro.db"

#: The only tables this adapter is allowed to read.  Everything else in macro.db
#: belongs to the owning project and is off-limits.
ALLOWED_TABLES = (
    "macro_series",
    "macro_calendar_history",
    "macro_calendar_events",
)

#: Columns each allowed table must expose for the adapter to be usable.
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "macro_series": ("series_id", "date", "value", "source", "fetched_ts"),
    "macro_calendar_history": (
        "series_id",
        "release_date",
        "event_title",
        "forecast_display",
        "forecast_value",
        "previous_display",
        "previous_value",
        "actual_display",
        "actual_value",
        "impact",
        "comparable",
        "source",
    ),
    "macro_calendar_events": (
        "event_key",
        "title",
        "country",
        "release_at",
        "impact",
    ),
}

#: SQLite header: offset of the 4-byte big-endian file change counter.
CHANGE_COUNTER_OFFSET = 24
CHANGE_COUNTER_SIZE = 4
_HEADER_READ_SIZE = CHANGE_COUNTER_OFFSET + CHANGE_COUNTER_SIZE

MAX_SNAPSHOT_RETRIES = 3


class OptionsdeckSeriesError(RuntimeError):
    """Base error for the optionsdeck macro adapter."""


class SnapshotError(OptionsdeckSeriesError):
    """Raised when a consistent snapshot of the source DB could not be taken."""


@dataclass(frozen=True)
class SeriesInfo:
    """One (series_id, source) pair present in ``macro_series``."""

    series_id: str
    source: str
    n_obs: int
    first_date: str | None
    last_date: str | None


@dataclass(frozen=True)
class Observation:
    """A single ``macro_series`` observation.

    ``date`` is the series' native period label and is **not** uniformly ISO:
    daily/monthly FRED series use ``YYYY-MM-DD``, DBnomics monthly series use
    ``YYYY-MM``, quarterly ones ``YYYY-Qn`` and IMF forecasts plain ``YYYY``.
    The format is stable *within* a series, so lexicographic range filters are
    well-defined per series.
    """

    date: str
    value: float | None


@dataclass(frozen=True)
class CalendarRelease:
    """A row of ``macro_calendar_history`` (one economic release).

    ``forecast_value`` / ``previous_value`` / ``actual_value`` are already REAL
    columns upstream -- they are exposed verbatim and never re-parsed from the
    ``*_display`` strings.  ``comparable`` flags whether the numeric value is a
    level directly comparable against an external authority series.
    """

    series_id: str
    country: str
    release_date: str
    event_title: str | None
    forecast_display: str | None
    forecast_value: float | None
    previous_display: str | None
    previous_value: float | None
    actual_display: str | None
    actual_value: float | None
    impact: str | None
    comparable: bool
    source: str


@dataclass(frozen=True)
class AvailabilityInfo:
    """Result of :meth:`OptionsdeckSeriesClient.available`.

    ``latest_observation_date`` / ``latest_calendar_release`` / ``fetched_at``
    exist so reports can footnote how stale the backbone is: the upstream
    collector runs twice a day, so ~12h staleness is normal, not a fault.
    """

    available: bool
    db_path: Path
    reason: str | None = None
    missing: tuple[str, ...] = field(default_factory=tuple)
    series_count: int | None = None
    latest_observation_date: str | None = None
    latest_calendar_release: str | None = None
    fetched_at: str | None = None

    def __bool__(self) -> bool:
        return self.available


# --- snapshot machinery -----------------------------------------------------

_SNAPSHOT_DIR: Path | None = None
#: (source path, mtime_ns, size) -> snapshot path, so one session copies once.
_SNAPSHOT_CACHE: dict[tuple[str, int, int], Path] = {}


def _snapshot_dir() -> Path:
    """Return (creating on first use) the process-scoped snapshot directory."""
    global _SNAPSHOT_DIR
    if _SNAPSHOT_DIR is None or not _SNAPSHOT_DIR.exists():
        _SNAPSHOT_DIR = Path(tempfile.mkdtemp(prefix="indepth-optionsdeck-"))
        atexit.register(_cleanup_snapshots)
    return _SNAPSHOT_DIR


def _cleanup_snapshots() -> None:
    """Remove the snapshot directory (registered with :mod:`atexit`)."""
    global _SNAPSHOT_DIR
    if _SNAPSHOT_DIR is not None:
        shutil.rmtree(_SNAPSHOT_DIR, ignore_errors=True)
        _SNAPSHOT_DIR = None
    _SNAPSHOT_CACHE.clear()


def _read_change_counter(path: Path) -> tuple[int, int]:
    """Return ``(change_counter, file_size)`` from the SQLite header.

    Opens the file read-only and reads the first 28 bytes -- no lock is taken and
    the file is never modified.
    """
    size = path.stat().st_size
    with open(path, "rb") as fh:
        header = fh.read(_HEADER_READ_SIZE)
    if len(header) < _HEADER_READ_SIZE:
        raise SnapshotError(f"{path} is too small to be a SQLite database")
    counter = int.from_bytes(
        header[CHANGE_COUNTER_OFFSET : CHANGE_COUNTER_OFFSET + CHANGE_COUNTER_SIZE],
        "big",
    )
    return counter, size


def _take_snapshot(src: Path) -> Path:
    """Copy ``src`` to the snapshot dir, retrying until the copy is not torn."""
    stat = src.stat()
    key = (str(src), stat.st_mtime_ns, stat.st_size)
    cached = _SNAPSHOT_CACHE.get(key)
    if cached is not None and cached.exists():
        logger.debug("optionsdeck snapshot cache hit: %s", cached)
        return cached

    dest_dir = _snapshot_dir()
    dest = dest_dir / f"{src.stem}-{os.getpid()}-{stat.st_mtime_ns}.db"

    for attempt in range(1, MAX_SNAPSHOT_RETRIES + 1):
        before = _read_change_counter(src)
        shutil.copyfile(src, dest)
        after = _read_change_counter(src)
        if before == after:
            _SNAPSHOT_CACHE[key] = dest
            logger.debug("optionsdeck snapshot taken: %s -> %s", src, dest)
            return dest
        logger.warning(
            "torn snapshot of %s (change counter %s -> %s), retry %d/%d",
            src,
            before,
            after,
            attempt,
            MAX_SNAPSHOT_RETRIES,
        )
        dest.unlink(missing_ok=True)

    raise SnapshotError(
        f"could not take a consistent snapshot of {src} after "
        f"{MAX_SNAPSHOT_RETRIES} attempts (writer active)"
    )


def _resolve_db_path(db_path: Path | str | None) -> Path:
    """Constructor argument wins, then ``OPTIONSDECK_MACRO_DB``, then default."""
    if db_path is not None:
        return Path(db_path).expanduser()
    env = os.environ.get(ENV_DB_PATH)
    if env:
        return Path(env).expanduser()
    return DEFAULT_DB_PATH


def _iso_from_epoch_ms(value: int | float | None) -> str | None:
    if not value:
        return None
    return (
        datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


class OptionsdeckSeriesClient:
    """Read-only accessor for the optionsdeck macro backbone.

    Usage::

        client = OptionsdeckSeriesClient()
        info = client.available()
        if info:
            obs = client.get_series("M.RCH_A.CP00.EA", start="2024-01")

    :meth:`available` never raises -- it degrades to ``available=False`` with a
    reason so callers can fall back.  The query methods raise
    :class:`OptionsdeckSeriesError` on a missing/unreadable database, so gate
    them behind :meth:`available`.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = _resolve_db_path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._snapshot_path: Path | None = None

    # --- connection ---------------------------------------------------------

    @property
    def snapshot_path(self) -> Path | None:
        """Path of the snapshot currently backing this client (if connected)."""
        return self._snapshot_path

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if not self.db_path.exists():
            raise OptionsdeckSeriesError(f"macro DB not found: {self.db_path}")
        snapshot = _take_snapshot(self.db_path)
        conn = sqlite3.connect(f"file:{snapshot}?immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        self._conn = conn
        self._snapshot_path = snapshot
        return conn

    def refresh(self) -> None:
        """Drop the current connection so the next call re-snapshots the source."""
        self.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._snapshot_path = None

    def __enter__(self) -> OptionsdeckSeriesClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- availability -------------------------------------------------------

    def available(self) -> AvailabilityInfo:
        """Check the DB is present and has the expected tables/columns.

        Never raises: any failure is reported as ``available=False`` with a
        reason and logged as a warning, so pipelines degrade gracefully.
        """
        if not self.db_path.exists():
            reason = f"macro DB not found: {self.db_path}"
            logger.warning("optionsdeck backbone unavailable — %s", reason)
            return AvailabilityInfo(False, self.db_path, reason=reason)

        try:
            conn = self._connect()
            missing: list[str] = []
            for table in ALLOWED_TABLES:
                # table names come from the ALLOWED_TABLES constant, never from
                # user input, so interpolation here is safe.
                cols = {
                    row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
                }
                if not cols:
                    missing.append(table)
                    continue
                missing.extend(
                    f"{table}.{col}"
                    for col in REQUIRED_COLUMNS[table]
                    if col not in cols
                )
            if missing:
                reason = "missing tables/columns: " + ", ".join(missing)
                logger.warning("optionsdeck backbone unavailable — %s", reason)
                return AvailabilityInfo(
                    False, self.db_path, reason=reason, missing=tuple(missing)
                )

            row = conn.execute(
                "SELECT COUNT(DISTINCT series_id) AS n, "
                "       MAX(CASE WHEN LENGTH(date) = 10 THEN date END) AS last_obs, "
                "       MAX(fetched_ts) AS fetched_ts "
                "FROM macro_series"
            ).fetchone()
            last_release = conn.execute(
                "SELECT MAX(release_date) AS d FROM macro_calendar_history"
            ).fetchone()
        except OptionsdeckSeriesError as exc:
            logger.warning("optionsdeck backbone unavailable — %s", exc)
            return AvailabilityInfo(False, self.db_path, reason=str(exc))
        except (sqlite3.Error, OSError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            logger.warning("optionsdeck backbone unavailable — %s", reason)
            return AvailabilityInfo(False, self.db_path, reason=reason)

        return AvailabilityInfo(
            True,
            self.db_path,
            series_count=row["n"] if row else 0,
            latest_observation_date=row["last_obs"] if row else None,
            latest_calendar_release=last_release["d"] if last_release else None,
            fetched_at=_iso_from_epoch_ms(row["fetched_ts"] if row else None),
        )

    # --- queries ------------------------------------------------------------

    def list_series(self) -> list[SeriesInfo]:
        """Return every ``(series_id, source)`` pair with its coverage.

        A series ingested from more than one source yields one row per source.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT series_id, source, COUNT(*) AS n_obs, "
            "       MIN(date) AS first_date, MAX(date) AS last_date "
            "FROM macro_series "
            "GROUP BY series_id, source "
            "ORDER BY series_id, source"
        ).fetchall()
        return [
            SeriesInfo(
                series_id=row["series_id"],
                source=row["source"],
                n_obs=row["n_obs"],
                first_date=row["first_date"],
                last_date=row["last_date"],
            )
            for row in rows
        ]

    def get_series(
        self,
        series_id: str,
        start: str | None = None,
        end: str | None = None,
        include_null: bool = False,
    ) -> list[Observation]:
        """Return observations for ``series_id``, ascending by date.

        ``start``/``end`` are inclusive and compared lexicographically against
        the series' native period label (see :class:`Observation`), so they must
        use the same format as the series itself (e.g. ``"2024-01"`` for a
        monthly DBnomics series, ``"2024-01-01"`` for a daily FRED one).

        Rows whose ``value`` is NULL (holidays / not-yet-published prints) are
        dropped unless ``include_null`` is set.
        """
        conn = self._connect()
        sql = ["SELECT date, value FROM macro_series WHERE series_id = ?"]
        params: list[object] = [series_id]
        if not include_null:
            sql.append("AND value IS NOT NULL")
        if start is not None:
            sql.append("AND date >= ?")
            params.append(start)
        if end is not None:
            sql.append("AND date <= ?")
            params.append(end)
        sql.append("ORDER BY date")
        rows = conn.execute(" ".join(sql), params).fetchall()
        return [Observation(date=row["date"], value=row["value"]) for row in rows]

    def get_calendar_history(
        self,
        country: str | None = None,
        series_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[CalendarRelease]:
        """Return calendar release rows, ascending by ``release_date``.

        Schema note: ``macro_calendar_history`` has **no country column** --
        country lives in the ``series_id`` prefix (``EU.HICP_YOY`` ->
        ``EU``).  The ``country`` filter is therefore a prefix match on
        ``series_id`` and the returned ``country`` field is derived the same way.

        ``start``/``end`` filter ``release_date`` (ISO ``YYYY-MM-DD``), inclusive.
        """
        conn = self._connect()
        sql = [
            "SELECT series_id, release_date, event_title, forecast_display, "
            "       forecast_value, previous_display, previous_value, "
            "       actual_display, actual_value, impact, comparable, source "
            "FROM macro_calendar_history WHERE 1 = 1"
        ]
        params: list[object] = []
        if country is not None:
            sql.append("AND series_id LIKE ?")
            params.append(f"{country.upper()}.%")
        if series_id is not None:
            sql.append("AND series_id = ?")
            params.append(series_id)
        if start is not None:
            sql.append("AND release_date >= ?")
            params.append(start)
        if end is not None:
            sql.append("AND release_date <= ?")
            params.append(end)
        sql.append("ORDER BY release_date, series_id")
        rows = conn.execute(" ".join(sql), params).fetchall()
        return [
            CalendarRelease(
                series_id=row["series_id"],
                country=_country_of(row["series_id"]),
                release_date=row["release_date"],
                event_title=row["event_title"],
                forecast_display=row["forecast_display"],
                forecast_value=row["forecast_value"],
                previous_display=row["previous_display"],
                previous_value=row["previous_value"],
                actual_display=row["actual_display"],
                actual_value=row["actual_value"],
                impact=row["impact"],
                comparable=bool(row["comparable"]),
                source=row["source"],
            )
            for row in rows
        ]


def _country_of(series_id: str) -> str:
    """Derive the country prefix of a calendar series id (``EU.HICP_YOY`` -> ``EU``)."""
    head, _, rest = series_id.partition(".")
    return head if rest else ""
