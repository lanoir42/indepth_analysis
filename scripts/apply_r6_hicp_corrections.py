"""Correct the vendor-shifted EU HICP rows in ``data/macro_calendar.db`` (R6).

Background (R-1 §4 -> R6 primary-source reconciliation, 2026-08-06)
-------------------------------------------------------------------
The seeded vendor stream (``source='seed:jblanked'``) publishes euro-area
HICP as a single interleaved flash/final chain. R6 fetched every Eurostat
euro-indicators press release for 2025-12 .. 2026-07 and established:

* the vendor's **headline flash** rows are stamped with a release slot that
  is **two reference months too late**, starting with the 2026-02-04 release.
  The values are genuine Eurostat prints -- they are simply attached to the
  wrong release date (2026-01's 1.7% lands in the 2026-03-31 slot, and so
  on). The break coincides exactly with 2026-01, the HICP methodology
  discontinuity month (ECOICOP v2 / 2025=100 rebasing), which is where the
  vendor's reference-month bookkeeping evidently slipped;
* the vendor's **headline final** ``actual`` values match Eurostat exactly
  across the whole window (2026-02-25 -> 1.7, 2026-03-18 -> 1.9,
  2026-04-16 -> 2.6). Only their ``forecast`` is contaminated, because it
  carries the *shifted* flash value -- which makes the stored surprise
  (``actual - forecast``) fictitious even though the actual is sound;
* the vendor's **core flash** chain is correct except for a single
  mislabelled row at 2026-02-04 (stored 2.4, Eurostat 2026-01 core flash
  2.2).

The three corrective actions below follow directly from that:

============================  =========================================
action                        rows
============================  =========================================
delete                        4x ``CPI Flash Estimate y/y`` (2026-02-04,
                              2026-03-03, 2026-03-31, 2026-04-30) +
                              1x ``Core CPI Flash Estimate y/y``
                              (2026-02-04) -- the actual contradicts the
                              Eurostat print published on that date, so
                              the row is not recoverable by re-labelling
                              (its correct slot is already occupied).
forecast -> NULL              3x ``Final CPI y/y`` (2026-02-25,
                              2026-03-18, 2026-04-16) -- actual verified
                              against Eurostat and **kept**; only the
                              contaminated forecast is cleared.
                              ``CalendarEvent.surprise`` returns None
                              when either side is missing, so these rows
                              drop out of ``surprise_stats`` history
                              automatically while remaining available as
                              a level series.
============================  =========================================

Nothing is corrected by *rewriting* a value: every action either removes a
row or removes a field. A re-labelled row would need a release date that is
already taken by another row in the same track, and inventing forecasts is
not something a reconciliation script gets to do.

Safety
------
Rows are never addressed by a hard-coded ``event_id``. Each target is
resolved by ``(country, title, release date, source='seed:jblanked')``,
then cross-checked three ways before it is touched:

1. the stored ``actual`` must equal the value R6 recorded for that row;
2. the stored ``actual`` must **disagree** with (delete targets) or
   **agree** with (NULL targets) the Eurostat golden print for the
   reference month the row's release slot implies;
3. the resolved ``event_id`` must start with the prefix the R6 worksheet
   listed for that row.

Any mismatch aborts the whole run before a single statement executes --
a DB that has drifted from the worksheet is a DB whose corrections were
computed against a different reality.

Usage::

    # Dry run (default): resolve + validate targets, print the plan,
    # then run the golden/chain verification against the CURRENT db.
    uv run python scripts/apply_r6_hicp_corrections.py

    # Verification only -- no plan, exits 1 while violations remain.
    uv run python scripts/apply_r6_hicp_corrections.py --verify

    # Apply. Run only after the dry run has been reviewed.
    uv run python scripts/apply_r6_hicp_corrections.py --commit
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from bgilib.macro.models import CalendarEvent
from bgilib.macro.xsource import chain_audit

DEFAULT_DB = Path("data/macro_calendar.db")

COUNTRY = "EUR"
VENDOR_SOURCE = "seed:jblanked"

#: Equality tolerance for one-decimal percent series (values are stored as
#: floats, so 2.6 - 2.6 is not necessarily exactly 0.0).
EPS = 0.005

#: Tolerance for the flash-track ``previous[i] ~= actual[i-1]`` link.
#:
#: Not ``EPS``: a *flash* release restates the prior reference month using
#: the value known at the time, which is that month's **final** print, while
#: the prior flash row's ``actual`` is its **flash** print. The two legally
#: differ by the Eurostat flash->final revision, structurally within 0.1%p
#: (R6 §3 confirms |revision| <= 0.1 for every 2026 reference month). So the
#: link tolerance is that envelope plus rounding slack. Anything wider is a
#: genuine break -- the 2026 shift produced gaps of -0.4 and +0.9.
CHAIN_TOL = 0.15


@dataclass(frozen=True)
class GoldenPrint:
    """Eurostat's published prints for one reference month (R6 §1).

    ``None`` means R6 recorded the cell as unconfirmed or not yet
    published; those cells are skipped by the verifier rather than
    guessed at.
    """

    flash: float | None
    final: float | None
    core_flash: float | None
    core_final: float | None


#: Golden series, keyed by **reference month** (not release date). Sourced
#: verbatim from ``r6_primary_hicp_2026.md`` §1, every cell a direct quote
#: from a Eurostat euro-indicators press release.
GOLDEN: dict[str, GoldenPrint] = {
    "2025-12": GoldenPrint(flash=2.0, final=1.9, core_flash=None, core_final=2.3),
    "2026-01": GoldenPrint(flash=1.7, final=1.7, core_flash=2.2, core_final=None),
    "2026-02": GoldenPrint(flash=1.9, final=1.9, core_flash=2.4, core_final=2.4),
    "2026-03": GoldenPrint(flash=2.5, final=2.6, core_flash=2.3, core_final=2.3),
    "2026-04": GoldenPrint(flash=3.0, final=3.0, core_flash=2.2, core_final=2.2),
    "2026-05": GoldenPrint(flash=3.2, final=3.2, core_flash=2.5, core_final=2.6),
    "2026-06": GoldenPrint(flash=2.8, final=2.8, core_flash=2.4, core_final=2.4),
    "2026-07": GoldenPrint(flash=2.9, final=None, core_flash=2.5, core_final=None),
}


@dataclass(frozen=True)
class Track:
    """One ForexFactory title, and how to read it against :data:`GOLDEN`."""

    #: ``flash`` (month-turn release) or ``final`` (mid-month release) --
    #: determines how a release date maps to a reference month.
    vintage: str
    #: Attribute of :class:`GoldenPrint` holding this track's truth value.
    golden_field: str


TRACKS: dict[str, Track] = {
    "CPI Flash Estimate y/y": Track("flash", "flash"),
    "Final CPI y/y": Track("final", "final"),
    "Core CPI Flash Estimate y/y": Track("flash", "core_flash"),
    "Final Core CPI y/y": Track("final", "core_final"),
}

#: Headline track used for the chain audit. The *final* track cannot be
#: chain-audited: the vendor's final rows carry the same reference month's
#: flash print in ``previous`` (not the prior month's final), so a
#: final-to-final ``previous[i] ~= actual[i-1]`` link is meaningless by
#: construction and would flag every ordinary month-on-month move. The
#: final track is verified against :data:`GOLDEN` only.
CHAIN_TRACK = "CPI Flash Estimate y/y"


@dataclass(frozen=True)
class DeleteTarget:
    """A row to remove, with everything needed to prove it is the right row."""

    title: str
    release_date: date
    #: ``actual`` the R6 worksheet recorded for this row.
    expected_actual: float
    #: ``event_id`` prefix from the R6 worksheet. ``None`` where the
    #: worksheet listed no id (core flash row), in which case the golden
    #: mismatch and the expected actual carry the identification alone.
    expected_event_id_prefix: str | None
    reason: str


@dataclass(frozen=True)
class NullForecastTarget:
    """A row whose ``forecast`` is cleared while its ``actual`` is kept."""

    title: str
    release_date: date
    expected_actual: float
    expected_forecast: float
    reason: str


_SHIFT_REASON = (
    "vendor ref-month +2 shift (2026-01 ECOICOP v2 break); actual contradicts "
    "the Eurostat print published on this date"
)

DELETE_TARGETS: tuple[DeleteTarget, ...] = (
    DeleteTarget(
        "CPI Flash Estimate y/y", date(2026, 2, 4), 2.1, "aacbdd63", _SHIFT_REASON
    ),
    DeleteTarget(
        "CPI Flash Estimate y/y", date(2026, 3, 3), 2.0, "7f0c846f", _SHIFT_REASON
    ),
    DeleteTarget(
        "CPI Flash Estimate y/y", date(2026, 3, 31), 1.7, "60165889", _SHIFT_REASON
    ),
    DeleteTarget(
        "CPI Flash Estimate y/y", date(2026, 4, 30), 1.9, "fec9fac4", _SHIFT_REASON
    ),
    DeleteTarget(
        "Core CPI Flash Estimate y/y",
        date(2026, 2, 4),
        2.4,
        None,
        "isolated mislabel; Eurostat 2026-01 core flash is 2.2",
    ),
)

NULL_FORECAST_TARGETS: tuple[NullForecastTarget, ...] = (
    NullForecastTarget("Final CPI y/y", date(2026, 2, 25), 1.7, 2.1, _SHIFT_REASON),
    NullForecastTarget("Final CPI y/y", date(2026, 3, 18), 1.9, 2.0, _SHIFT_REASON),
    NullForecastTarget("Final CPI y/y", date(2026, 4, 16), 2.6, 1.7, _SHIFT_REASON),
)


class CorrectionAbortError(RuntimeError):
    """A target failed validation -- the run stops before touching the DB."""


# --------------------------------------------------------------------------
# db access
# --------------------------------------------------------------------------


def _connect(db_path: Path, *, readonly: bool) -> sqlite3.Connection:
    """Open ``db_path``; ``readonly`` uses a URI connection that cannot write.

    Dry runs and ``--verify`` must not be able to modify the DB even by
    accident, which a plain ``sqlite3.connect`` would permit.
    """
    if not db_path.exists():
        raise SystemExit(f"target DB not found: {db_path}")
    uri = f"file:{db_path}?mode=ro" if readonly else str(db_path)
    conn = sqlite3.connect(uri, uri=readonly)
    conn.row_factory = sqlite3.Row
    return conn


def _to_event(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        event_id=row["event_id"],
        country=row["country"],
        title=row["title"],
        impact=row["impact"],
        datetime_utc=datetime.fromisoformat(row["datetime_utc"]),
        forecast=row["forecast"],
        previous=row["previous"],
        actual=row["actual"],
        is_released=bool(row["is_released"]),
        source=row["source"],
        raw_time=row["raw_time"],
        raw_date=row["raw_date"],
    )


def _vendor_rows(conn: sqlite3.Connection, title: str) -> list[CalendarEvent]:
    """Every vendor-seeded row for one title, chronologically."""
    rows = conn.execute(
        "SELECT * FROM calendar_events "
        "WHERE country = ? AND title = ? AND source = ? "
        "ORDER BY datetime_utc ASC",
        (COUNTRY, title, VENDOR_SOURCE),
    ).fetchall()
    return [_to_event(r) for r in rows]


def _resolve(
    conn: sqlite3.Connection, title: str, release_date: date
) -> CalendarEvent:
    """Find the single vendor row for ``(title, release_date)``.

    Deliberately keyed on the release *date*, not on ``event_id``: the id is
    a hash of (country, title, datetime) and hard-coding it would make the
    script silently no-op if the seeder's id scheme ever changed, instead of
    failing loudly.
    """
    matches = [
        e
        for e in _vendor_rows(conn, title)
        if e.datetime_utc.date() == release_date
    ]
    if len(matches) != 1:
        raise CorrectionAbortError(
            f"expected exactly 1 {VENDOR_SOURCE} row for {COUNTRY} {title!r} "
            f"on {release_date.isoformat()}, found {len(matches)}"
        )
    return matches[0]


# --------------------------------------------------------------------------
# reference-month inference + golden lookup
# --------------------------------------------------------------------------


def _prev_month(d: date) -> str:
    year, month = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    return f"{year}-{month:02d}"


def reference_month(release_date: date, vintage: str) -> str:
    """Map a release date to the reference month it reports on.

    Mirrors the release windows in
    :mod:`indepth_analysis.skills.euro_macro.calendar_title_map`: the euro
    area flash lands on the last working days of the reference month itself
    (day >= 26) or slips into the first days of the next one (day <= 8),
    while the final lands mid-following-month (days 14-25) and therefore
    always reports the previous month.

    Raises:
        CorrectionAbortError: if the date falls outside its vintage's window --
            a row we cannot place is a row we must not judge.
    """
    day = release_date.day
    if vintage == "flash":
        if day >= 26:
            return f"{release_date.year}-{release_date.month:02d}"
        if day <= 8:
            return _prev_month(release_date)
        raise CorrectionAbortError(
            f"flash release {release_date.isoformat()} is outside the "
            "month-turn window (day 26-31 or 1-8)"
        )
    if vintage == "final":
        if 14 <= day <= 25:
            return _prev_month(release_date)
        raise CorrectionAbortError(
            f"final release {release_date.isoformat()} is outside the "
            "mid-month window (day 14-25)"
        )
    raise CorrectionAbortError(f"unknown vintage {vintage!r}")


def golden_for(title: str, release_date: date) -> tuple[str, float | None]:
    """Return ``(reference_month, truth value)`` for one row's slot.

    The value is ``None`` when R6 has no confirmed print for that cell.
    """
    track = TRACKS[title]
    ref = reference_month(release_date, track.vintage)
    entry = GOLDEN.get(ref)
    if entry is None:
        return ref, None
    return ref, getattr(entry, track.golden_field)


def _eq(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < EPS


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedDelete:
    target: DeleteTarget
    event: CalendarEvent
    reference_month: str
    golden: float | None


@dataclass(frozen=True)
class ResolvedNull:
    target: NullForecastTarget
    event: CalendarEvent
    reference_month: str
    golden: float | None


@dataclass(frozen=True)
class Plan:
    deletes: list[ResolvedDelete]
    nulls: list[ResolvedNull]
    #: Per-target notes about the event_id cross-check, for the audit trail.
    id_checks: list[str]


def build_plan(conn: sqlite3.Connection) -> Plan:
    """Resolve and validate every target. Raises before any DB write."""
    deletes: list[ResolvedDelete] = []
    nulls: list[ResolvedNull] = []
    id_checks: list[str] = []
    problems: list[str] = []

    for target in DELETE_TARGETS:
        event = _resolve(conn, target.title, target.release_date)
        ref, truth = golden_for(target.title, target.release_date)
        label = f"{target.title} {target.release_date.isoformat()}"

        if not _eq(event.actual, target.expected_actual):
            problems.append(
                f"{label}: stored actual={event.actual} != worksheet "
                f"actual={target.expected_actual}"
            )
        if truth is None:
            problems.append(
                f"{label}: no confirmed Eurostat print for reference month "
                f"{ref} -- cannot justify a deletion"
            )
        elif _eq(event.actual, truth):
            problems.append(
                f"{label}: stored actual={event.actual} AGREES with the "
                f"Eurostat {ref} print ({truth}) -- this row is correct and "
                "must not be deleted"
            )
        if target.expected_event_id_prefix is not None:
            if event.event_id.startswith(target.expected_event_id_prefix):
                id_checks.append(
                    f"  OK      {label}: event_id {event.event_id} matches "
                    f"worksheet prefix {target.expected_event_id_prefix}"
                )
            else:
                problems.append(
                    f"{label}: resolved event_id {event.event_id} does not "
                    f"match worksheet prefix {target.expected_event_id_prefix}"
                )
        else:
            id_checks.append(
                f"  n/a     {label}: worksheet listed no event_id; identified "
                f"by actual={event.actual} vs Eurostat {ref} {truth} "
                f"(resolved {event.event_id})"
            )
        deletes.append(ResolvedDelete(target, event, ref, truth))

    for null_target in NULL_FORECAST_TARGETS:
        event = _resolve(conn, null_target.title, null_target.release_date)
        ref, truth = golden_for(null_target.title, null_target.release_date)
        label = f"{null_target.title} {null_target.release_date.isoformat()}"

        if not _eq(event.actual, null_target.expected_actual):
            problems.append(
                f"{label}: stored actual={event.actual} != worksheet "
                f"actual={null_target.expected_actual}"
            )
        if not _eq(event.actual, truth):
            problems.append(
                f"{label}: stored actual={event.actual} does NOT match the "
                f"Eurostat {ref} final print ({truth}) -- the premise for "
                "keeping this actual fails"
            )
        if event.forecast is None:
            id_checks.append(f"  SKIP    {label}: forecast already NULL")
        elif not _eq(event.forecast, null_target.expected_forecast):
            problems.append(
                f"{label}: stored forecast={event.forecast} != worksheet "
                f"forecast={null_target.expected_forecast}"
            )
        nulls.append(ResolvedNull(null_target, event, ref, truth))

    if problems:
        raise CorrectionAbortError(
            "target validation failed -- no changes applied:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    return Plan(deletes=deletes, nulls=nulls, id_checks=id_checks)


def apply_plan(conn: sqlite3.Connection, plan: Plan) -> None:
    """Execute the plan in a single transaction."""
    with conn:
        for item in plan.deletes:
            conn.execute(
                "DELETE FROM calendar_events WHERE event_id = ?",
                (item.event.event_id,),
            )
        for null_item in plan.nulls:
            conn.execute(
                "UPDATE calendar_events SET forecast = NULL, updated_at = ? "
                "WHERE event_id = ?",
                (datetime.now(UTC).timestamp(), null_item.event.event_id),
            )


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    check: str
    detail: str


@dataclass(frozen=True)
class Verification:
    violations: list[Violation]
    #: Rows compared against a confirmed golden print.
    golden_checked: int
    #: Rows skipped because R6 has no confirmed print for their slot.
    golden_uncovered: list[str]
    chain_links: int
    #: (country, title) -> surprise-usable row count, as the DB stands now.
    group_n: dict[str, int]


def _surprise_n(events: list[CalendarEvent]) -> int:
    return sum(1 for e in events if e.is_released and e.surprise is not None)


def verify(conn: sqlite3.Connection) -> Verification:
    """Regression-check the EUR HICP tracks against the R6 golden series.

    Four independent checks:

    1. **golden actual** -- every vendor row whose slot has a confirmed
       Eurostat print must carry that print as its ``actual``;
    2. **golden forecast envelope** -- a *final* row's forecast is a
       consensus for a number the flash already published, so it cannot sit
       further than the revision envelope from that flash. Catches
       shift-contaminated forecasts generically (it does not catch all
       three of them -- check 3 is the targeted post-condition);
    3. **cleared forecasts** -- the three final rows R6 identified as
       forecast-contaminated must have ``forecast IS NULL``, so that
       ``CalendarEvent.surprise`` is None and ``surprise_stats`` skips them;
    4. **chain audit** -- ``previous[i] ~= actual[i-1]`` along the headline
       flash track, via :func:`bgilib.macro.xsource.chain_audit`.
    """
    violations: list[Violation] = []
    uncovered: list[str] = []
    checked = 0

    for title, track in TRACKS.items():
        for event in _vendor_rows(conn, title):
            release_date = event.datetime_utc.date()
            if event.actual is None:
                continue
            ref, truth = golden_for(title, release_date)
            label = f"{title} {release_date.isoformat()} (ref {ref})"
            if truth is None:
                uncovered.append(label)
                continue
            checked += 1
            if not _eq(event.actual, truth):
                violations.append(
                    Violation(
                        "golden-actual",
                        f"{label}: stored actual={event.actual} != Eurostat "
                        f"{truth}",
                    )
                )
            if track.vintage != "final" or event.forecast is None:
                continue
            golden_entry = GOLDEN[ref]
            flash_truth = (
                golden_entry.flash
                if track.golden_field == "final"
                else golden_entry.core_flash
            )
            if flash_truth is None:
                continue
            gap = event.forecast - flash_truth
            if abs(gap) > CHAIN_TOL:
                violations.append(
                    Violation(
                        "golden-forecast-envelope",
                        f"{label}: forecast={event.forecast} is {gap:+.1f} from "
                        f"the published {ref} flash ({flash_truth}), beyond the "
                        f"+/-{CHAIN_TOL} revision envelope -- surprise is fictitious",
                    )
                )

    for null_target in NULL_FORECAST_TARGETS:
        try:
            event = _resolve(conn, null_target.title, null_target.release_date)
        except CorrectionAbortError as exc:
            violations.append(Violation("cleared-forecast", str(exc)))
            continue
        if event.forecast is not None:
            violations.append(
                Violation(
                    "cleared-forecast",
                    f"{null_target.title} "
                    f"{null_target.release_date.isoformat()}: forecast="
                    f"{event.forecast} still set (R6: shift-contaminated, "
                    "must be NULL so the row leaves sigma history)",
                )
            )

    chain_rows = chain_audit(_vendor_rows(conn, CHAIN_TRACK), tol=CHAIN_TOL)
    for row in chain_rows:
        if not row.ok:
            violations.append(
                Violation(
                    "chain-break",
                    f"{CHAIN_TRACK} {row.prev_label} -> {row.label}: "
                    f"prior actual {row.expected} vs previous {row.observed} "
                    f"(gap {row.gap:+.1f})",
                )
            )

    group_n = {
        title: _surprise_n(
            [
                _to_event(r)
                for r in conn.execute(
                    "SELECT * FROM calendar_events WHERE country = ? AND title = ?",
                    (COUNTRY, title),
                ).fetchall()
            ]
        )
        for title in TRACKS
    }

    return Verification(
        violations=violations,
        golden_checked=checked,
        golden_uncovered=uncovered,
        chain_links=len(chain_rows),
        group_n=group_n,
    )


def projected_group_n(conn: sqlite3.Connection, plan: Plan) -> dict[str, int]:
    """Surprise-usable ``n`` per track once ``plan`` is applied.

    Computed in memory against the current DB so a dry run can report the
    post-correction sample sizes that ``surprise_stats`` will see (its
    ``min_history_points`` default is 6).
    """
    deleted = {item.event.event_id for item in plan.deletes}
    nulled = {item.event.event_id for item in plan.nulls}
    out: dict[str, int] = {}
    for title in TRACKS:
        rows = conn.execute(
            "SELECT * FROM calendar_events WHERE country = ? AND title = ?",
            (COUNTRY, title),
        ).fetchall()
        n = 0
        for row in rows:
            if row["event_id"] in deleted:
                continue
            event = _to_event(row)
            if event.event_id in nulled:
                # forecast cleared -> CalendarEvent.surprise becomes None
                continue
            if event.is_released and event.surprise is not None:
                n += 1
        out[title] = n
    return out


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def print_plan(plan: Plan, *, committed: bool) -> None:
    print()
    print("=" * 76)
    print(f"apply_r6_hicp_corrections: {'COMMIT' if committed else 'DRY RUN'}")
    print("=" * 76)
    print(f"delete targets:          {len(plan.deletes)}")
    print(f"forecast->NULL targets:  {len(plan.nulls)}")
    print()

    print(f"-- delete ({len(plan.deletes)}) --")
    for item in plan.deletes:
        e = item.event
        print(
            f"  {e.event_id}  {e.datetime_utc.date().isoformat()}  "
            f"{e.title:28}  f={e.forecast} p={e.previous} a={e.actual}"
        )
        print(
            f"      ref {item.reference_month}: Eurostat {item.golden} vs "
            f"stored {e.actual}  |  {item.target.reason}"
        )
    print()

    print(f"-- forecast -> NULL ({len(plan.nulls)}) --")
    for null_item in plan.nulls:
        e = null_item.event
        print(
            f"  {e.event_id}  {e.datetime_utc.date().isoformat()}  "
            f"{e.title:28}  f={e.forecast} -> NULL, a={e.actual} (kept)"
        )
        print(
            f"      ref {null_item.reference_month}: actual matches Eurostat "
            f"{null_item.golden}; forecast carries the shifted flash print"
        )
    print()

    print("-- event_id cross-check vs R6 worksheet --")
    for line in plan.id_checks:
        print(line)
    print()


def print_verification(v: Verification, *, header: str) -> None:
    print("=" * 76)
    print(header)
    print("=" * 76)
    print(f"golden comparisons run:   {v.golden_checked}")
    print(f"golden-uncovered rows:    {len(v.golden_uncovered)} (skipped, not judged)")
    print(f"chain links audited:      {v.chain_links} (tol={CHAIN_TOL})")
    print(f"violations:               {len(v.violations)}")
    print()
    if v.violations:
        for violation in v.violations:
            print(f"  [{violation.check}] {violation.detail}")
        print()
    if v.golden_uncovered:
        print("-- no confirmed Eurostat print for these slots (skipped) --")
        for label in v.golden_uncovered:
            print(f"  {label}")
        print()
    print("-- surprise-usable n per (EUR, title) --")
    for title, n in v.group_n.items():
        mark = "ok " if n >= 6 else "LOW"
        print(f"  {mark} {title:32} n={n}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply the R6 primary-source corrections to the seeded EU HICP "
            "rows (delete shifted flash rows, clear contaminated final "
            "forecasts). Default is a dry run."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually apply the corrections (default: dry run)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "verification only: compare the DB against the R6 golden series "
            "and audit the flash chain. Exits 1 while violations remain."
        ),
    )
    args = parser.parse_args(argv)

    if args.verify and args.commit:
        parser.error("--verify and --commit are mutually exclusive")

    if args.verify:
        conn = _connect(args.db, readonly=True)
        try:
            result = verify(conn)
        finally:
            conn.close()
        print_verification(result, header=f"R6 verification: {args.db}")
        return 1 if result.violations else 0

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
            result = verify(conn)
            print_verification(result, header="R6 verification: AFTER correction")
            if result.violations:
                print("WARNING: violations remain after correction", file=sys.stderr)
                return 1
            return 0

        result = verify(conn)
        print_verification(
            result, header="R6 verification: BEFORE correction (current DB)"
        )
        projected = projected_group_n(conn, plan)
        print("-- projected surprise-usable n AFTER correction --")
        for title, n in projected.items():
            delta = n - result.group_n[title]
            mark = "ok " if n >= 6 else "LOW"
            print(f"  {mark} {title:32} n={result.group_n[title]} -> {n} ({delta:+d})")
        print()
        print("(dry run -- nothing written; re-run with --commit to apply)")
        print()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
