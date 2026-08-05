"""Collapse the ``source='html'`` duplicate rows left behind by the backfill bug.

Background (R-1 reconciliation Section 6, R4 follow-up)
------------------------------------------------------
``data/macro_calendar.db`` holds 585 ``source='html'`` rows that describe only
117 real releases. Every release is stored five times, once per week the
2026-04-29 ``macro backfill --weeks 5`` run walked, each copy carrying a
different (wrong) date and therefore a different ``event_id``:

    EUR Spanish Unemployment Rate  f=9.8 a=10.8  2026-03-30
                                                 2026-04-06
                                                 2026-04-13
                                                 2026-04-20
                                                 2026-04-27   <- 5 rows, 1 release

Two independent defects combined to produce this (both fixed in bgilib
``html_scraper`` / ``parsers``; this script only cleans up the residue):

1. ``_parse_html`` looked for the day label in ``td.calendar__date`` on
   day-breaker rows, but Forex Factory puts it in a bare ``td.calendar__cell``.
   The selector never matched, so ``current_date`` stayed at its initial value
   -- the *requested week's Monday* -- for all 117 rows of the page.
2. Forex Factory answers ``?week=MMDDYYYY`` with the **current** week when the
   request carries no session. All five weekly URLs returned the same page
   (Sun Apr 26 - Sat May 2, 2026), verified here: the five cached bodies parse
   to byte-identical event tuples.

So the same page was parsed five times and stamped with five different fake
Mondays. Because ``event_id = sha256(country|title|datetime_utc)``, each pass
minted a fresh primary key and ``upsert_events`` inserted rather than updated.

Measured damage: of the 65 html rows that carry both a forecast and an actual
(the only ones ``surprise_stats`` consumes), 52 are duplicates of 13 real
releases. ``JPY Unemployment Rate`` is the group where the pollution actually
reaches a statistic -- five identical ``+0.10`` surprises inflate it from n=8
to n=13 and deflate sigma from 0.146 to 0.112.

Choosing which row to keep
--------------------------
Rows are grouped by ``(country, title, forecast, actual, raw_time)`` (NULL
treated as a value) and then split into clusters of rows within
``--max-gap-days`` (35) of each other, so two genuine prints of the same
indicator months apart are never merged. ``raw_time`` is part of the key
because value-less rows -- "President Trump Speaks" appears three times in one
page -- would otherwise be indistinguishable from each other; and where the
cache proves a key really does cover several releases, the cluster is split
again so each one keeps a row. Within a cluster the survivor is picked by the
strongest evidence available:

``cache``   The winning evidence here. ``http_cache`` still holds the five raw
            Forex Factory bodies. Re-parsing them with the *fixed* parser
            recovers each release's true datetime; the cluster row closest to
            it survives. This is a reconstruction of the real release date, not
            a heuristic.
``source``  Fallback when the page body is no longer cached: another source
            (``json`` / ``seed:jblanked``) reporting the same country/title with
            the same actual dates the release for us; keep the nearest row.
``latest``  Last resort. ``backfill_history`` walks week-Mondays *forward* and
            FF serves the current week, so the newest stamp in an artefact
            cluster is the one whose requested week actually overlaps the page
            that was served. Keeping the latest is therefore the least-wrong
            choice, and the cluster's own shape (identical values, identical
            time-of-day, exact 7-day spacing) is what identifies it as an
            artefact in the first place.

The kept row's date may still be off by a day or two -- the fix is not to
rewrite dates here (that would change ``event_id``, i.e. delete + re-insert
under a new primary key) but to let the corrected scraper re-collect. This
script's job is only to stop one release from counting five times.

Usage::

    # Dry run (default) -- prints every keep/delete decision, writes nothing.
    uv run python scripts/cleanup_html_duplicates.py

    # Restrict to the rows that actually feed surprise_stats.
    uv run python scripts/cleanup_html_duplicates.py --usable-only

    # Actually delete.
    uv run python scripts/cleanup_html_duplicates.py --commit
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger("cleanup_html_duplicates")

DEFAULT_DB = Path("data/macro_calendar.db")
DEFAULT_MAX_GAP_DAYS = 35
HTML_SOURCE = "html"

#: Grouping key: same indicator reporting the same numbers.
GroupKey = tuple[str, str, float | None, float | None]
#: Grouping key plus the wall-clock slot, so two different events that happen to
#: share a key (typically value-less rows such as "President Trump Speaks", which
#: appears three times in one page) are not merged into each other.
ClusterKey = tuple[str, str, float | None, float | None, str]


def make_cluster_key(
    country: str,
    title: str,
    forecast: float | None,
    actual: float | None,
    raw_time: str | None,
) -> ClusterKey:
    return (country, title, forecast, actual, (raw_time or "").strip().lower())


@dataclass(frozen=True)
class Row:
    """One ``calendar_events`` row, reduced to what the decision needs."""

    event_id: str
    country: str
    title: str
    forecast: float | None
    previous: float | None
    actual: float | None
    dt: datetime
    raw_date: str | None
    raw_time: str | None

    @property
    def key(self) -> GroupKey:
        return (self.country, self.title, self.forecast, self.actual)

    @property
    def cluster_key(self) -> ClusterKey:
        return make_cluster_key(
            self.country, self.title, self.forecast, self.actual, self.raw_time
        )


@dataclass
class Decision:
    """The verdict for one duplicate cluster."""

    keep: Row
    delete: list[Row]
    evidence: str
    truth: datetime | None = None


@dataclass
class Summary:
    html_rows: int = 0
    considered: int = 0
    clusters: int = 0
    duplicate_clusters: int = 0
    rows_deleted: int = 0
    by_evidence: dict[str, int] = field(default_factory=lambda: defaultdict(int))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _connect(db_path: Path, *, writable: bool) -> sqlite3.Connection:
    if writable:
        conn = sqlite3.connect(db_path)
    else:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_dt(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def load_html_rows(conn: sqlite3.Connection, *, usable_only: bool) -> list[Row]:
    sql = (
        "SELECT event_id, country, title, forecast, previous, actual, "
        "datetime_utc, raw_date, raw_time FROM calendar_events WHERE source = ?"
    )
    if usable_only:
        sql += " AND forecast IS NOT NULL AND actual IS NOT NULL"
    sql += " ORDER BY country, title, datetime_utc"
    return [
        Row(
            event_id=str(r["event_id"]),
            country=str(r["country"]),
            title=str(r["title"]),
            forecast=r["forecast"],
            previous=r["previous"],
            actual=r["actual"],
            dt=_parse_dt(str(r["datetime_utc"])),
            raw_date=r["raw_date"],
            raw_time=r["raw_time"],
        )
        for r in conn.execute(sql, (HTML_SOURCE,))
    ]


CrossSource = dict[tuple[str, str], list[tuple[datetime, float | None]]]


def load_cross_source_dates(conn: sqlite3.Connection) -> CrossSource:
    """(country, title) -> [(release datetime, actual)] from non-html sources."""
    out: dict[tuple[str, str], list[tuple[datetime, float | None]]] = defaultdict(list)
    sql = (
        "SELECT country, title, actual, datetime_utc FROM calendar_events "
        "WHERE source <> ? AND actual IS NOT NULL"
    )
    for r in conn.execute(sql, (HTML_SOURCE,)):
        out[(str(r["country"]), str(r["title"]))].append(
            (_parse_dt(str(r["datetime_utc"])), r["actual"])
        )
    return out


def reconstruct_truth_from_cache(
    conn: sqlite3.Connection,
) -> dict[ClusterKey, list[datetime]]:
    """Re-parse the cached Forex Factory pages with the *fixed* parser.

    Returns the real release datetimes keyed the same way the html rows are
    grouped. Returns an empty mapping (and logs why) if the cache is gone or
    bgilib/bs4 are unavailable -- the caller then falls back to weaker evidence.
    """
    try:
        from bgilib.macro.html_scraper import HTMLCalendarScraper
    except ImportError as exc:  # pragma: no cover - environment guard
        logger.warning("cache reconstruction unavailable (%s)", exc)
        return {}

    truth: dict[ClusterKey, list[datetime]] = defaultdict(list)
    pages = 0
    for r in conn.execute(
        "SELECT url, body FROM http_cache WHERE url LIKE '%forexfactory.com/calendar%'"
    ):
        url, body = str(r["url"]), str(r["body"])
        anchor = _week_anchor_from_url(url)
        if anchor is None:
            continue
        try:
            events = HTMLCalendarScraper.parse_html(body, anchor)
        except Exception as exc:  # noqa: BLE001 - a bad cache entry must not abort cleanup
            logger.warning("could not re-parse cached page %s: %s", url, exc)
            continue
        pages += 1
        for ev in events:
            key = make_cluster_key(
                ev.country, ev.title, ev.forecast, ev.actual, ev.raw_time
            )
            truth[key].append(ev.datetime_utc)
    logger.info("re-parsed %d cached Forex Factory page(s) for ground truth", pages)
    return truth


def _week_anchor_from_url(url: str) -> date | None:
    """Extract the ``?week=MMDDYYYY`` anchor. Only used for year inference."""
    marker = "week="
    idx = url.rfind(marker)
    if idx < 0:
        return None
    token = url[idx + len(marker):][:8]
    try:
        return datetime.strptime(token, "%m%d%Y").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------


def cluster_rows(rows: list[Row], max_gap_days: int) -> list[list[Row]]:
    """Split same-key rows into clusters of mutually-near dates.

    Chained on the gap between consecutive dates, so a 5-week artefact run
    (7-day steps) stays one cluster while two genuine prints of the same
    indicator a quarter apart do not.
    """
    ordered = sorted(rows, key=lambda r: r.dt)
    clusters: list[list[Row]] = []
    current: list[Row] = []
    limit = timedelta(days=max_gap_days)
    for row in ordered:
        if current and row.dt - current[-1].dt > limit:
            clusters.append(current)
            current = []
        current.append(row)
    if current:
        clusters.append(current)
    return clusters


def decide(
    cluster: list[Row],
    *,
    truth: dict[ClusterKey, list[datetime]],
    cross: CrossSource,
) -> Decision:
    """Pick the survivor of a duplicate cluster, strongest evidence first."""
    candidates = truth.get(cluster[0].cluster_key) or []
    if candidates:
        anchor = _nearest(candidates, cluster)
        keep = min(cluster, key=lambda r: (abs(r.dt - anchor), -r.dt.timestamp()))
        return Decision(keep, [r for r in cluster if r is not keep], "cache", anchor)

    same_print = [
        dt
        for dt, actual in cross.get((cluster[0].country, cluster[0].title), [])
        if cluster[0].actual is not None and actual == cluster[0].actual
    ]
    if same_print:
        anchor = _nearest(same_print, cluster)
        keep = min(cluster, key=lambda r: (abs(r.dt - anchor), -r.dt.timestamp()))
        return Decision(keep, [r for r in cluster if r is not keep], "source", anchor)

    keep = max(cluster, key=lambda r: r.dt)
    return Decision(keep, [r for r in cluster if r is not keep], "latest", None)


def _nearest(anchors: list[datetime], cluster: list[Row]) -> datetime:
    """The anchor closest to the cluster, in case a page holds repeat prints."""
    centre = min(cluster, key=lambda r: r.dt).dt
    return min(anchors, key=lambda a: abs(a - centre))


def split_by_truth(cluster: list[Row], anchors: list[datetime]) -> list[list[Row]]:
    """Re-partition a cluster so each reconstructed release keeps its own row.

    A single page can legitimately contain several releases that share the whole
    grouping key. When the cache tells us how many distinct releases there really
    are, honour that count instead of collapsing them all into one.
    """
    distinct = sorted(set(anchors))
    if len(distinct) < 2:
        return [cluster]
    buckets: dict[datetime, list[Row]] = defaultdict(list)
    for row in cluster:
        buckets[min(distinct, key=lambda a: abs(a - row.dt))].append(row)
    return [buckets[a] for a in distinct if buckets[a]]


def plan(
    rows: list[Row],
    *,
    truth: dict[ClusterKey, list[datetime]],
    cross: CrossSource,
    max_gap_days: int,
) -> tuple[list[Decision], Summary]:
    grouped: dict[ClusterKey, list[Row]] = defaultdict(list)
    for row in rows:
        grouped[row.cluster_key].append(row)

    def _order(k: ClusterKey) -> tuple[str, str, bool, float, str]:
        return (k[0], k[1], k[2] is None, k[2] or 0.0, k[4])

    decisions: list[Decision] = []
    summary = Summary(considered=len(rows))
    for key in sorted(grouped, key=_order):
        anchors = truth.get(key) or []
        for cluster in cluster_rows(grouped[key], max_gap_days):
            for part in split_by_truth(cluster, anchors):
                summary.clusters += 1
                if len(part) < 2:
                    continue
                decision = decide(part, truth=truth, cross=cross)
                decisions.append(decision)
                summary.duplicate_clusters += 1
                summary.rows_deleted += len(decision.delete)
                summary.by_evidence[decision.evidence] += 1
    return decisions, summary


# ---------------------------------------------------------------------------
# Reporting / writing
# ---------------------------------------------------------------------------


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def report(decisions: list[Decision], summary: Summary) -> None:
    print("=" * 96)
    print("source='html' duplicate cleanup plan")
    print("=" * 96)
    print(
        f"html rows in db: {summary.html_rows}   considered: {summary.considered}   "
        f"clusters: {summary.clusters}   "
        f"duplicate clusters: {summary.duplicate_clusters}"
    )
    print()
    for i, d in enumerate(decisions, 1):
        k = d.keep
        head = (
            f"[{i:>2}] {k.country} {k.title}  "
            f"f={_fmt(k.forecast)} a={_fmt(k.actual)}"
        )
        truth = f"  true release={d.truth:%Y-%m-%d %H:%MZ}" if d.truth else ""
        print(f"{head}   ({len(d.delete) + 1} rows, evidence={d.evidence}{truth})")
        off = f"  [{abs(k.dt - d.truth).days}d off]" if d.truth else ""
        print(
            f"     KEEP   {k.dt:%Y-%m-%d %H:%MZ}  "
            f"raw={k.raw_date} {k.raw_time or ''}  {k.event_id}{off}"
        )
        for r in sorted(d.delete, key=lambda x: x.dt):
            print(
                f"     DELETE {r.dt:%Y-%m-%d %H:%MZ}  "
                f"raw={r.raw_date} {r.raw_time or ''}  {r.event_id}"
            )
        print()

    print("-" * 96)
    print(f"rows to delete: {summary.rows_deleted}")
    print(
        "rows remaining (html): "
        f"{summary.html_rows - summary.rows_deleted}"
    )
    evidence = ", ".join(f"{k}={v}" for k, v in sorted(summary.by_evidence.items()))
    print(f"evidence used: {evidence or 'n/a'}")


def apply_deletions(db_path: Path, decisions: list[Decision]) -> int:
    ids = [r.event_id for d in decisions for r in d.delete]
    if not ids:
        return 0
    conn = _connect(db_path, writable=True)
    try:
        with conn:
            conn.executemany(
                "DELETE FROM calendar_events WHERE event_id = ? AND source = ?",
                [(eid, HTML_SOURCE) for eid in ids],
            )
        return len(ids)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collapse source='html' duplicate rows in the macro calendar DB. "
            "Dry-run by default."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"target sqlite db (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually delete the duplicate rows (default: dry run, read-only)",
    )
    parser.add_argument(
        "--usable-only",
        action="store_true",
        help=(
            "only consider rows with both a forecast and an actual "
            "(the rows surprise_stats reads)"
        ),
    )
    parser.add_argument(
        "--max-gap-days",
        type=int,
        default=DEFAULT_MAX_GAP_DAYS,
        help=(
            "max day gap between consecutive rows of one duplicate cluster "
            f"(default: {DEFAULT_MAX_GAP_DAYS})"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.db.exists():
        logger.error("db not found: %s", args.db)
        return 1

    conn = _connect(args.db, writable=False)
    try:
        summary_total = conn.execute(
            "SELECT count(*) FROM calendar_events WHERE source = ?", (HTML_SOURCE,)
        ).fetchone()[0]
        rows = load_html_rows(conn, usable_only=args.usable_only)
        truth = reconstruct_truth_from_cache(conn)
        cross = load_cross_source_dates(conn)
    finally:
        conn.close()

    decisions, summary = plan(
        rows, truth=truth, cross=cross, max_gap_days=args.max_gap_days
    )
    summary.html_rows = summary_total
    report(decisions, summary)

    if not args.commit:
        print("\n(dry run -- nothing written; pass --commit to delete)")
        return 0

    deleted = apply_deletions(args.db, decisions)
    print(f"\ncommitted: deleted {deleted} row(s) from {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
