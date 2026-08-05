"""Backfill the 2026 euro-area HICP series from Eurostat primary sources (R6, option B).

``apply_r6_hicp_corrections.py`` removed the vendor rows whose reference month
was mislabelled. That left the 2026 headline HICP history correct but *thin*:
six surprise points, all from reference months 2025-07..2025-12, i.e. entirely
from the calm pre-shift regime, with the 2026 energy-driven re-acceleration
missing. This script refills that gap from the R6 golden table
(``scratchpad/r6_primary_hicp_2026.md`` -- every cell a direct quote from a
Eurostat euro-indicators press release), in three operations.

Operation 1 -- attach a golden ``actual`` to a real-consensus feed row
---------------------------------------------------------------------
Two ForexFactory ``json`` rows carry a genuine market consensus but never got
their actual (our collector saw the calendar entry, not the print). Filling in
Eurostat's number turns each into a usable surprise point. Scope is the EUR
**headline** flash only; core HICP is out of scope for this pass.

**Guardrail 1 -- provenance.** An attached row's ``source`` becomes
``json+golden:r6``, not ``json``. These rows are half feed, half Eurostat, and
they must be **excluded from any future feed-vs-Eurostat cross-audit**:
checking a value we ourselves copied out of Eurostat against Eurostat is a
circular argument that would manufacture false confidence in the vendor feed.
The compound source string is what makes that exclusion mechanical rather than
remembered. (``apply_r6_hicp_corrections.verify`` already reads only
``source='seed:jblanked'``, so it is unaffected either way.)

**Guardrail 3 -- the forecast may be stale.** ForexFactory's ``forecast`` for
this indicator is suspect: the same 3.0 sits in the 2026-04-30 slot (actual
3.0), the 2026-03-30 slot (actual 2.5) and the 2026-07-01 slot (actual 2.8),
which looks like a carried-forward placeholder rather than a re-polled
consensus (R-1 section 4.4). A stale forecast makes each attached surprise
partly an artefact of ForexFactory's bookkeeping.

We attach anyway, and the reason is that sigma is a *relative* scale, not an
absolute one. Every future alert is scored as ``(actual - forecast) / sigma``
against the **same** ForexFactory forecast field that produced the history. If
that field is systematically stale, both the yardstick and the thing being
measured inherit the same defect, and the ratio stays self-consistent -- a
release that misses the FF forecast by an unusual amount still scores as
unusual. What we must not do is mix scales: pairing an Eurostat-derived actual
with a *different* forecast source, or comparing these z-scores against sigma
built from a cleaner consensus, would break exactly that self-consistency.
The two attached rows are therefore reported under
"review-flagged (stale-forecast suspicion)" in the run summary, so the caveat
travels with the data instead of living only in this docstring.

Operation 2 -- insert golden prints that never had a consensus row
------------------------------------------------------------------
Six Eurostat prints (three flash, three final) have no feed row at all. They
are inserted as ``source='golden:eurostat'`` with **``forecast`` NULL**:

* ``CalendarEvent.surprise`` returns None without a forecast, so these rows
  contribute nothing to ``surprise_stats`` -- no invented consensus ever
  becomes a sigma input;
* Section B skips any row where forecast or actual is None
  (``macro_sections`` builder), so they never surface as "news";
* what they do provide is a complete *level* series for reference, and a
  chain anchor: a future feed row's ``previous`` can now be audited against
  the Eurostat ``actual`` of the release before it.

``previous`` is left NULL for the same reason a forecast is. The only value we
could put there is another cell of the golden table, and a chain audit run
over links we derived from that table can only ever pass -- a circular check
that looks like evidence. Leaving it NULL keeps the one direction of the chain
audit that is genuinely informative (feed ``previous`` vs golden ``actual``)
and drops the direction that is not. ``chain_audit`` skips a link whenever
either side is None, so nothing is manufactured.

Operation 3 -- drop the 2026-04-27 html rows that shadow a json twin
--------------------------------------------------------------------
**Guardrail 2.** ForexFactory answers ``?week=`` with the *current* week when
the request has no session, so the 2026-04-29 backfill stamped a whole page of
upcoming releases with a fake 2026-04-27 Monday (see
``cleanup_html_duplicates.py``, which collapsed the five-fold copies but could
not fix the date). For six CPI releases the json feed later stored the *same*
release under its true date. Both copies are currently unreleased
(``actual IS NULL``), so they are inert today -- but the moment any backfill
fills in actuals, the release is counted twice, in the same
``(country, title)`` bucket that feeds sigma. Removing the mis-dated html copy
now is what keeps this script's own operation 1 from being the thing that
double-counts.

Only the six CPI rows in the chief's scope are touched. The rest of the
mis-dated html page is reported as an out-of-scope count, not silently
cleaned.

Safety
------
No ``event_id`` is ever hard-coded as the *lookup* key. Each target is
resolved by ``(country, title, release date, source)``, cross-checked against
the R6 golden table and against the expected field values, and only then
compared to the id the chief's worksheet listed. Any mismatch aborts the whole
run before a single statement executes.

Usage::

    uv run python scripts/backfill_golden_hicp.py            # dry run (default)
    uv run python scripts/backfill_golden_hicp.py --commit   # apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import fmean, pstdev

from bgilib.macro.models import CalendarEvent
from bgilib.macro.parsers import event_id as make_event_id

# Sibling script: single source of truth for the Eurostat golden table and for
# release-date -> reference-month inference. Duplicating either here is how the
# two drift apart. Python already puts this file's directory on sys.path when
# the script is run directly; the insert only covers exotic invocations.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from apply_r6_hicp_corrections import (  # noqa: E402
    COUNTRY,
    CorrectionAbortError,
    _eq,
    _to_event,
    golden_for,
)

DEFAULT_DB = Path("data/macro_calendar.db")

#: Source stamp for a feed row whose actual came from Eurostat, not the feed.
#: Deliberately compound: it keeps the row's feed provenance visible while
#: marking it ineligible for feed-vs-Eurostat cross-audits (guardrail 1).
ATTACHED_SOURCE = "json+golden:r6"

#: Source stamp for a row that exists only because Eurostat published a print.
GOLDEN_SOURCE = "golden:eurostat"

#: Impact for inserted golden rows. Matches the seeder's placeholder: the
#: history pool is impact-agnostic and these rows never reach a display table
#: (forecast is NULL, which Section B filters on).
GOLDEN_IMPACT = "Medium"

#: Collision radius when deciding whether a golden print already has a row.
#: Same +/-1 day the seeder's dedupe uses -- a feed and a publisher can
#: disagree by a day about when a release "happened".
COLLISION_DAYS = 1

#: How far from the fake html date to look for the json twin of the same
#: release. The mis-dated page was scraped on a Monday for releases landing
#: that same week, so the true date is a few days later at most.
TWIN_WINDOW_DAYS = 5

#: The fake Monday the ?week= bug stamped onto a whole page of releases.
HTML_FAKE_DATE = date(2026, 4, 27)


# --------------------------------------------------------------------------
# targets
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AttachTarget:
    """A feed row that should receive Eurostat's actual."""

    title: str
    release_date: date
    expected_forecast: float
    expected_previous: float
    #: Reference month the release slot implies; re-derived and cross-checked.
    reference_month: str
    #: Eurostat print for that reference month; cross-checked against GOLDEN.
    golden_actual: float
    expected_event_id: str


@dataclass(frozen=True)
class InsertTarget:
    """An Eurostat print with no feed row anywhere."""

    title: str
    release_date: date
    reference_month: str
    golden_actual: float


@dataclass(frozen=True)
class HtmlDupTarget:
    """A mis-dated html row shadowing a json row for the same release."""

    title: str
    expected_event_id: str


ATTACH_TARGETS: tuple[AttachTarget, ...] = (
    AttachTarget(
        title="CPI Flash Estimate y/y",
        release_date=date(2026, 4, 30),
        expected_forecast=3.0,
        expected_previous=2.5,
        reference_month="2026-04",
        golden_actual=3.0,
        expected_event_id="8b40a032048d21da",
    ),
    AttachTarget(
        title="CPI Flash Estimate y/y",
        release_date=date(2026, 7, 1),
        expected_forecast=3.0,
        expected_previous=3.2,
        reference_month="2026-06",
        golden_actual=2.8,
        expected_event_id="ef182b663b3ce408",
    ),
)

INSERT_TARGETS: tuple[InsertTarget, ...] = (
    InsertTarget("CPI Flash Estimate y/y", date(2026, 3, 31), "2026-03", 2.5),
    InsertTarget("CPI Flash Estimate y/y", date(2026, 6, 2), "2026-05", 3.2),
    InsertTarget("CPI Flash Estimate y/y", date(2026, 7, 31), "2026-07", 2.9),
    InsertTarget("Final CPI y/y", date(2026, 5, 20), "2026-04", 3.0),
    InsertTarget("Final CPI y/y", date(2026, 6, 17), "2026-05", 3.2),
    InsertTarget("Final CPI y/y", date(2026, 7, 17), "2026-06", 2.8),
)

HTML_DUP_TARGETS: tuple[HtmlDupTarget, ...] = (
    HtmlDupTarget("CPI Flash Estimate y/y", "5ac4be1a479bac01"),
    HtmlDupTarget("Core CPI Flash Estimate y/y", "a67813671ca80991"),
    HtmlDupTarget("German Prelim CPI m/m", "90e9f9e9f2b8e452"),
    HtmlDupTarget("French Prelim CPI m/m", "80818578b252646c"),
    HtmlDupTarget("Spanish Flash CPI y/y", "2586a0fc74cd2abd"),
    HtmlDupTarget("Italian Prelim CPI m/m", "416a23014742b384"),
)


# --------------------------------------------------------------------------
# db access
# --------------------------------------------------------------------------


def _connect(db_path: Path, *, readonly: bool) -> sqlite3.Connection:
    """Open ``db_path``; a dry run gets a connection that physically cannot write."""
    if not db_path.exists():
        raise SystemExit(f"target DB not found: {db_path}")
    uri = f"file:{db_path}?mode=ro" if readonly else str(db_path)
    conn = sqlite3.connect(uri, uri=readonly)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(
    conn: sqlite3.Connection, title: str, *, source: str | None = None
) -> list[CalendarEvent]:
    sql = "SELECT * FROM calendar_events WHERE country = ? AND title = ?"
    params: list[object] = [COUNTRY, title]
    if source is not None:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY datetime_utc ASC"
    return [_to_event(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def _one(
    conn: sqlite3.Connection, title: str, release_date: date, source: str
) -> CalendarEvent:
    matches = [
        e
        for e in _rows(conn, title, source=source)
        if e.datetime_utc.date() == release_date
    ]
    if len(matches) != 1:
        raise CorrectionAbortError(
            f"expected exactly 1 source={source!r} row for {COUNTRY} {title!r} "
            f"on {release_date.isoformat()}, found {len(matches)}"
        )
    return matches[0]


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedAttach:
    target: AttachTarget
    event: CalendarEvent


@dataclass(frozen=True)
class ResolvedInsert:
    target: InsertTarget
    event: CalendarEvent


@dataclass(frozen=True)
class SkippedInsert:
    target: InsertTarget
    collision: CalendarEvent


@dataclass(frozen=True)
class ResolvedHtmlDup:
    target: HtmlDupTarget
    event: CalendarEvent
    twin: CalendarEvent
    #: True when the twin restates ``previous`` differently -- expected FF
    #: churn between the mis-dated scrape and the true-dated json row, worth
    #: printing but not worth aborting on.
    previous_drift: bool


@dataclass(frozen=True)
class Plan:
    attaches: list[ResolvedAttach]
    inserts: list[ResolvedInsert]
    skipped_inserts: list[SkippedInsert]
    html_dups: list[ResolvedHtmlDup]
    #: Mis-dated html rows outside this pass's scope, for awareness only.
    out_of_scope_html: int
    notes: list[str] = field(default_factory=list)


def _check_golden(
    label: str,
    title: str,
    release_date: date,
    declared_month: str,
    declared_value: float,
    problems: list[str],
) -> None:
    """Re-derive the reference month and truth value; never trust the literal."""
    ref, truth = golden_for(title, release_date)
    if ref != declared_month:
        problems.append(
            f"{label}: release slot implies reference month {ref}, target "
            f"declares {declared_month}"
        )
    if truth is None:
        problems.append(f"{label}: no confirmed Eurostat print for {ref}")
    elif not _eq(truth, declared_value):
        problems.append(
            f"{label}: golden table has {truth} for {ref}, target declares "
            f"{declared_value}"
        )


def build_plan(conn: sqlite3.Connection) -> Plan:
    """Resolve and validate every target. Raises before any DB write."""
    problems: list[str] = []
    notes: list[str] = []

    # ---- operation 1: attach ------------------------------------------
    attaches: list[ResolvedAttach] = []
    for target in ATTACH_TARGETS:
        label = f"attach {target.title} {target.release_date.isoformat()}"
        event = _one(conn, target.title, target.release_date, "json")
        _check_golden(
            label,
            target.title,
            target.release_date,
            target.reference_month,
            target.golden_actual,
            problems,
        )
        if event.actual is not None:
            problems.append(
                f"{label}: row already carries actual={event.actual} -- "
                "attaching would overwrite a published value"
            )
        if event.is_released:
            problems.append(f"{label}: row is already marked released")
        if not _eq(event.forecast, target.expected_forecast):
            problems.append(
                f"{label}: forecast={event.forecast} != expected "
                f"{target.expected_forecast} -- the consensus this row was "
                "chosen for is not the one stored"
            )
        if not _eq(event.previous, target.expected_previous):
            problems.append(
                f"{label}: previous={event.previous} != expected "
                f"{target.expected_previous}"
            )
        if event.event_id != target.expected_event_id:
            problems.append(
                f"{label}: resolved event_id {event.event_id} != worksheet "
                f"{target.expected_event_id}"
            )
        attaches.append(ResolvedAttach(target, event))

    # ---- operation 2: insert ------------------------------------------
    inserts: list[ResolvedInsert] = []
    skipped: list[SkippedInsert] = []
    planned_ids = {a.event.event_id for a in attaches}
    for insert_target in INSERT_TARGETS:
        label = f"insert {insert_target.title} {insert_target.release_date.isoformat()}"
        _check_golden(
            label,
            insert_target.title,
            insert_target.release_date,
            insert_target.reference_month,
            insert_target.golden_actual,
            problems,
        )
        # Collision search deliberately ignores is_released: an unreleased
        # feed row occupying the slot means the release already has a home
        # (operation 1's case), and inserting beside it would double-count
        # the moment that row is filled in.
        collision = next(
            (
                e
                for e in _rows(conn, insert_target.title)
                if abs((e.datetime_utc.date() - insert_target.release_date).days)
                <= COLLISION_DAYS
            ),
            None,
        )
        if collision is not None:
            skipped.append(SkippedInsert(insert_target, collision))
            continue
        dt_utc = datetime(
            insert_target.release_date.year,
            insert_target.release_date.month,
            insert_target.release_date.day,
            tzinfo=UTC,
        )
        eid = make_event_id(COUNTRY, insert_target.title, dt_utc)
        if eid in planned_ids:
            problems.append(f"{label}: event_id {eid} collides within this batch")
        planned_ids.add(eid)
        inserts.append(
            ResolvedInsert(
                insert_target,
                CalendarEvent(
                    event_id=eid,
                    country=COUNTRY,
                    title=insert_target.title,
                    impact=GOLDEN_IMPACT,
                    datetime_utc=dt_utc,
                    forecast=None,
                    previous=None,
                    actual=insert_target.golden_actual,
                    is_released=True,
                    source=GOLDEN_SOURCE,
                    raw_time=None,
                    raw_date=insert_target.release_date.isoformat(),
                ),
            )
        )

    # ---- operation 3: html duplicates ---------------------------------
    html_dups: list[ResolvedHtmlDup] = []
    for dup_target in HTML_DUP_TARGETS:
        label = f"html-dup {dup_target.title}"
        try:
            event = _one(conn, dup_target.title, HTML_FAKE_DATE, "html")
        except CorrectionAbortError as exc:
            problems.append(f"{label}: {exc}")
            continue
        if event.actual is not None:
            problems.append(
                f"{label}: html row carries actual={event.actual} -- it is not "
                "the inert shadow copy this operation is scoped to"
            )
        twins = [
            e
            for e in _rows(conn, dup_target.title, source="json")
            if abs((e.datetime_utc.date() - HTML_FAKE_DATE).days) <= TWIN_WINDOW_DAYS
            and _eq(e.forecast, event.forecast)
        ]
        if len(twins) != 1:
            problems.append(
                f"{label}: expected exactly 1 json twin within "
                f"+/-{TWIN_WINDOW_DAYS}d carrying forecast={event.forecast}, "
                f"found {len(twins)} -- cannot prove this row is a duplicate"
            )
            continue
        twin = twins[0]
        if event.event_id != dup_target.expected_event_id:
            problems.append(
                f"{label}: resolved event_id {event.event_id} != worksheet "
                f"{dup_target.expected_event_id}"
            )
        drift = not _eq(event.previous, twin.previous)
        html_dups.append(ResolvedHtmlDup(dup_target, event, twin, drift))

    out_of_scope = _count_out_of_scope_html(conn, {t.title for t in HTML_DUP_TARGETS})
    if out_of_scope:
        notes.append(
            f"{out_of_scope} further mis-dated html row(s) on "
            f"{HTML_FAKE_DATE.isoformat()} also have a json twin but are "
            "outside this pass's CPI scope -- left untouched, not cleaned"
        )

    if problems:
        raise CorrectionAbortError(
            "target validation failed -- no changes applied:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    return Plan(
        attaches=attaches,
        inserts=inserts,
        skipped_inserts=skipped,
        html_dups=html_dups,
        out_of_scope_html=out_of_scope,
        notes=notes,
    )


def _count_out_of_scope_html(
    conn: sqlite3.Connection, in_scope_titles: set[str]
) -> int:
    """Count same-defect html rows this pass deliberately leaves alone."""
    rows = conn.execute(
        "SELECT * FROM calendar_events "
        "WHERE date(datetime_utc) = ? AND source = 'html' AND actual IS NULL",
        (HTML_FAKE_DATE.isoformat(),),
    ).fetchall()
    count = 0
    for row in rows:
        if row["title"] in in_scope_titles and row["country"] == COUNTRY:
            continue
        twin = conn.execute(
            "SELECT 1 FROM calendar_events "
            "WHERE country = ? AND title = ? AND source = 'json' "
            "AND abs(julianday(datetime_utc) - julianday(?)) <= ? LIMIT 1",
            (
                row["country"],
                row["title"],
                HTML_FAKE_DATE.isoformat(),
                TWIN_WINDOW_DAYS,
            ),
        ).fetchone()
        if twin is not None:
            count += 1
    return count


def apply_plan(conn: sqlite3.Connection, plan: Plan) -> None:
    """Execute the plan in a single transaction."""
    now = datetime.now(UTC).timestamp()
    with conn:
        for attach in plan.attaches:
            conn.execute(
                "UPDATE calendar_events "
                "SET actual = ?, is_released = 1, source = ?, updated_at = ? "
                "WHERE event_id = ?",
                (
                    attach.target.golden_actual,
                    ATTACHED_SOURCE,
                    now,
                    attach.event.event_id,
                ),
            )
        for insert in plan.inserts:
            e = insert.event
            conn.execute(
                "INSERT INTO calendar_events (event_id, country, title, impact, "
                "datetime_utc, forecast, previous, actual, is_released, source, "
                "raw_time, raw_date, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    e.event_id,
                    e.country,
                    e.title,
                    e.impact,
                    e.datetime_utc.isoformat(),
                    e.forecast,
                    e.previous,
                    e.actual,
                    int(e.is_released),
                    e.source,
                    e.raw_time,
                    e.raw_date,
                    now,
                ),
            )
        for dup in plan.html_dups:
            conn.execute(
                "DELETE FROM calendar_events WHERE event_id = ?",
                (dup.event.event_id,),
            )


# --------------------------------------------------------------------------
# statistics projection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupStat:
    n: int
    mean: float | None
    sigma: float | None
    surprises: list[float]


def _stat_of(events: list[CalendarEvent]) -> GroupStat:
    values = [
        e.surprise
        for e in events
        if e.is_released and e.surprise is not None
    ]
    if not values:
        return GroupStat(0, None, None, [])
    return GroupStat(len(values), fmean(values), pstdev(values), sorted(values))


def project_stats(
    conn: sqlite3.Connection, plan: Plan | None
) -> dict[str, tuple[GroupStat, GroupStat]]:
    """Return ``{title: (before, after)}`` surprise statistics.

    Computed in memory over the whole stored history for the group, which is
    what ``surprise_stats`` sees for these titles today (every row falls
    inside its 24-month window). ``plan`` of None reports the current state
    on both sides.
    """
    attach_by_id = (
        {a.event.event_id: a.target.golden_actual for a in plan.attaches}
        if plan
        else {}
    )
    deleted = {d.event.event_id for d in plan.html_dups} if plan else set()
    extra: dict[str, list[CalendarEvent]] = {}
    if plan:
        for insert in plan.inserts:
            extra.setdefault(insert.target.title, []).append(insert.event)

    titles = sorted(
        {t.title for t in ATTACH_TARGETS}
        | {t.title for t in INSERT_TARGETS}
        | {t.title for t in HTML_DUP_TARGETS}
    )
    out: dict[str, tuple[GroupStat, GroupStat]] = {}
    for title in titles:
        current = _rows(conn, title)
        after: list[CalendarEvent] = []
        for event in current:
            if event.event_id in deleted:
                continue
            if event.event_id in attach_by_id:
                event = CalendarEvent(
                    event_id=event.event_id,
                    country=event.country,
                    title=event.title,
                    impact=event.impact,
                    datetime_utc=event.datetime_utc,
                    forecast=event.forecast,
                    previous=event.previous,
                    actual=attach_by_id[event.event_id],
                    is_released=True,
                    source=ATTACHED_SOURCE,
                )
            after.append(event)
        after.extend(extra.get(title, []))
        out[title] = (_stat_of(current), _stat_of(after))
    return out


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def _fmt(stat: GroupStat) -> str:
    if stat.mean is None or stat.sigma is None:
        return f"n={stat.n:2d}  mean=   --    sigma=   --"
    return f"n={stat.n:2d}  mean={stat.mean:+.4f}  sigma={stat.sigma:.4f}"


def print_plan(plan: Plan, *, committed: bool) -> None:
    print()
    print("=" * 78)
    print(f"backfill_golden_hicp: {'COMMIT' if committed else 'DRY RUN'}")
    print("=" * 78)
    print(f"1. attach golden actual:   {len(plan.attaches)}")
    print(f"2. insert golden rows:     {len(plan.inserts)}")
    print(f"   insert skipped (slot occupied): {len(plan.skipped_inserts)}")
    print(f"3. delete mis-dated html:  {len(plan.html_dups)}")
    print()

    print(
        "-- 1. attach golden actual to real-consensus feed row "
        f"({len(plan.attaches)}) --"
    )
    for attach in plan.attaches:
        e, t = attach.event, attach.target
        print(
            f"  {e.event_id}  {e.datetime_utc.date().isoformat()}  {e.title}"
        )
        print(
            f"      f={e.forecast} p={e.previous} a=NULL -> a={t.golden_actual} "
            f"(Eurostat {t.reference_month} flash), is_released 0 -> 1"
        )
        print(f"      source {e.source!r} -> {ATTACHED_SOURCE!r}")
    print()

    print(f"-- 2. insert actual-only golden rows ({len(plan.inserts)}) --")
    for insert in plan.inserts:
        e = insert.event
        print(
            f"  {e.event_id}  {e.datetime_utc.date().isoformat()}  {e.title:24} "
            f"a={e.actual} (ref {insert.target.reference_month})  "
            f"f=NULL p=NULL src={e.source}"
        )
    if plan.skipped_inserts:
        print()
        print(f"  -- skipped, slot already occupied ({len(plan.skipped_inserts)}) --")
        for skip in plan.skipped_inserts:
            c = skip.collision
            print(
                f"    {skip.target.title} {skip.target.release_date.isoformat()}: "
                f"existing {c.event_id} at {c.datetime_utc.date().isoformat()} "
                f"(src={c.source}, a={c.actual})"
            )
    print()

    print(
        "-- 3. delete mis-dated html rows shadowing a json twin "
        f"({len(plan.html_dups)}) --"
    )
    for dup in plan.html_dups:
        e, twin = dup.event, dup.twin
        print(f"  {e.event_id}  {e.title:30} f={e.forecast} p={e.previous} a=NULL")
        drift = (
            f"  [previous restated {e.previous} -> {twin.previous}]"
            if dup.previous_drift
            else ""
        )
        print(
            f"      twin {twin.event_id} {twin.datetime_utc.date().isoformat()} "
            f"src={twin.source} f={twin.forecast} p={twin.previous}{drift}"
        )
    print()

    flagged = plan.attaches
    print(f"-- review-flagged (stale-forecast suspicion) ({len(flagged)}) --")
    print(
        "   ForexFactory carried the same forecast 3.0 across slots whose "
        "actuals were 2.5 / 3.0 / 2.8, so these forecasts may be "
        "carry-forward placeholders rather than polled consensus."
    )
    print(
        "   Attached regardless: future alerts are scored against the same FF "
        "forecast field, so scale and measurement stay self-consistent. Do "
        "NOT mix these z-scores with sigma built from another consensus source."
    )
    for attach in flagged:
        e, t = attach.event, attach.target
        print(
            f"  {e.event_id}  {e.datetime_utc.date().isoformat()}  "
            f"f={e.forecast} a={t.golden_actual}  "
            f"surprise={t.golden_actual - (e.forecast or 0.0):+.1f}"
        )
    print()

    if plan.notes:
        print("-- notes --")
        for note in plan.notes:
            print(f"  {note}")
        print()


def print_stats(
    projected: dict[str, tuple[GroupStat, GroupStat]], *, header: str
) -> None:
    print("-" * 78)
    print(header)
    print("-" * 78)
    for title, (before, after) in projected.items():
        changed = (before.n, before.mean, before.sigma) != (
            after.n,
            after.mean,
            after.sigma,
        )
        mark = "*" if changed else " "
        print(f"{mark} {COUNTRY} {title}")
        print(f"    before  {_fmt(before)}")
        print(f"    after   {_fmt(after)}")
        if changed and after.surprises:
            joined = ", ".join(f"{v:+.1f}" for v in after.surprises)
            print(f"    surprises after: [{joined}]")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill the 2026 euro-area HICP series from the R6 Eurostat "
            "golden table. Default is a dry run."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually apply the backfill (default: dry run)",
    )
    args = parser.parse_args(argv)

    conn = _connect(args.db, readonly=not args.commit)
    try:
        try:
            plan = build_plan(conn)
        except CorrectionAbortError as exc:
            print(f"ABORT: {exc}", file=sys.stderr)
            return 2
        print_plan(plan, committed=args.commit)

        if args.commit:
            apply_plan(conn, plan)
            print_stats(
                project_stats(conn, None), header="surprise statistics: AFTER backfill"
            )
            total = conn.execute("SELECT count(*) FROM calendar_events").fetchone()[0]
            print(f"calendar_events rows now: {total}")
            print()
            return 0

        print_stats(
            project_stats(conn, plan),
            header="surprise statistics: projected (in-memory, whole stored history)",
        )
        total = conn.execute("SELECT count(*) FROM calendar_events").fetchone()[0]
        net = len(plan.inserts) - len(plan.html_dups)
        print(f"calendar_events rows: {total} -> {total + net} ({net:+d})")
        print()
        print("(dry run -- nothing written; re-run with --commit to apply)")
        print()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
