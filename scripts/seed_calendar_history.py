"""Seed ``calendar_events`` with historical surprises from the optionsdeck backbone.

Fills the sigma-alert cold-start gap: :func:`bgilib.macro.storage.MacroStore
.query_events` only has ForexFactory rows since our own JSON-feed collector
started (2026-03-30), which is far short of the ``min_history_points=6``
:func:`indepth_analysis.skills.euro_macro.macro_alerts.surprise_stats` needs
per (country, title) pair. The optionsdeck project (``~/.optionsdeck-gb``)
has independently scraped JBlanked/faireconomy calendar releases back to
2025-07, covering the same indicators under different generic titles. This
script re-titles that history to ForexFactory's exact vocabulary and inserts
it as ``source='seed:jblanked'`` rows so :func:`surprise_stats` has enough
history to compute sigma without waiting eight more months for organic data.

Pipeline (see the module-level docstring of ``calendar_title_map`` for the
title-mapping rationale, and Advisor plan v2 Section 2b for the full spec):

1. Read every ``macro_calendar_history`` row with both a forecast and an
   actual value ("usable") via the read-only
   :class:`~indepth_analysis.data.optionsdeck_series.OptionsdeckSeriesClient`
   snapshot adapter (never opens the live optionsdeck DB).
2. Resolve each row's ForexFactory title + release vintage (flash/final/...)
   via :func:`calendar_title_map.classify_release`. Rows with no mapping or
   no matching release-date window are quarantined, not guessed.
3. Quality-gate the survivors:
   a. per-indicator plausibility range (:data:`PLAUSIBILITY_RANGES`);
   b. per-(country, title) outlier screen on the surprise
      (``actual - forecast``): flag rows outside ``median ± 3*IQR`` of their
      group. Groups with too few points (:data:`MIN_IQR_GROUP_SIZE`) or zero
      IQR (see the docstring of :func:`_iqr_gate`) are passed through
      unscreened rather than risk false positives.
4. Dedupe against rows already in the target DB: same (country, ForexFactory
   title) with a release date within +/-1 day is skipped, so the 2026-03-30
   onward overlap between our organic collector and the JBlanked backfill is
   not double-counted.
5. Insert the survivors as :class:`~bgilib.macro.models.CalendarEvent` rows
   (``impact='Medium'`` fixed, ``datetime_utc`` = release date at 00:00:00Z --
   the source has no intraday release time, and Section B of the monthly
   report excludes ``source LIKE 'seed:%'`` rows from its display query, so
   neither the impact filter nor the placeholder time distorts anything a
   reader sees; both only feed :func:`surprise_stats` history, which is
   impact- and time-of-day-agnostic).

Every quarantined/deduped/inserted row is accounted for in the run summary --
nothing is silently dropped.

Usage::

    # Dry run (default) -- prints the summary, writes nothing.
    uv run python scripts/seed_calendar_history.py

    # Actually insert into data/macro_calendar.db.
    uv run python scripts/seed_calendar_history.py --commit

    # Diagnostic: print the surprise_stats() snapshot of the target DB
    # (no seeding). Used for the before/after verification report.
    uv run python scripts/seed_calendar_history.py --stats-before 2026-09-01
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from bgilib.macro.models import CalendarEvent
from bgilib.macro.parsers import event_id
from bgilib.macro.storage import MacroStore

from indepth_analysis.data.optionsdeck_series import (
    CalendarRelease,
    OptionsdeckSeriesClient,
)
from indepth_analysis.skills.euro_macro import calendar_title_map as ctm

logger = logging.getLogger("seed_calendar_history")

#: A usable source row paired with its resolved ForexFactory title/vintage.
Classified = tuple[CalendarRelease, ctm.FFTitleMapping]

DEFAULT_TARGET_DB = Path("data/macro_calendar.db")

#: Fixed impact for seeded rows. surprise_stats()/query_events() history reads
#: never filter by impact by default (macro_alerts.surprise_stats docstring:
#: "Filter candidates by impact instead, at the call site" -- the *history*
#: pool is deliberately impact-agnostic), and Section B excludes
#: source='seed:%' rows from its own impact-filtered display query. So this
#: placeholder has no effect on any statistic or table a reader sees.
SEED_IMPACT = "Medium"
SEED_SOURCE = "seed:jblanked"

#: Plausibility ranges keyed by the JBlanked series-id suffix (the part after
#: the last '.', e.g. "HICP_YOY" from "EU.HICP_YOY"). Applied identically
#: across countries because the suffix already encodes the unit (a YoY %, an
#: index level, ...), not the country. ``None`` means "no fixed bound -- rely
#: on the per-group IQR screen only", used where the *unit itself* varies too
#: much across countries for one range to make sense (trade balances: EUR/USD
#: report low-double-digit billions, JPY reports hundreds of billions yen).
PLAUSIBILITY_RANGES: dict[str, tuple[float, float] | None] = {
    # YoY consumer price indices: -2..15 per the backbone plan (covers every
    # observed post-2020 disinflation/inflation episode across EUR/USD/JPY
    # with headroom, while still catching a mis-scaled or garbage value).
    "HICP_YOY": (-2.0, 15.0),
    "CORE_CPI_YOY": (-2.0, 15.0),
    "CPI_YOY": (-2.0, 15.0),
    "CORECPI_YOY": (-2.0, 15.0),
    "TOKYO_CORECPI": (-2.0, 15.0),
    # Month-over-month price indices: single-digit moves are already extreme.
    "CPI_MM": (-5.0, 5.0),
    "CORECPI_MM": (-5.0, 5.0),
    "CORE_PCE_MM": (-5.0, 5.0),
    "PPI_MM": (-5.0, 5.0),
    # PPI y/y rides commodity/energy base effects harder than CPI y/y.
    "PPI_YOY": (-15.0, 30.0),
    # Unemployment rate: a percentage, structurally bounded well inside 0-30.
    "UNRATE": (0.0, 30.0),
    # Diffusion-index PMIs: 0-100 by construction, realistic range 20-80.
    "PMI_MFG": (20.0, 80.0),
    "PMI_SVC": (20.0, 80.0),
    "ISM_MFG": (20.0, 80.0),
    "ISM_SVC": (20.0, 80.0),
    # Quarterly GDP growth: -15..15 per the backbone plan (wide enough for
    # the 2020 COVID print, tight enough to catch a units error).
    "GDP_QOQ": (-15.0, 15.0),
    # Monthly retail/production indices.
    "RETAIL_MM": (-15.0, 15.0),
    "CORE_RETAIL_MM": (-15.0, 15.0),
    "INDPRO_MM": (-15.0, 15.0),
    "RETAIL_YOY": (-30.0, 30.0),
    # BoJ Tankan diffusion index is bounded to [-100, 100] by construction.
    "TANKAN_MFG": (-100.0, 100.0),
    # US JOLTS job openings, reported in millions; historical range ~4-12M.
    "JOLTS": (0.0, 20.0),
    # US NFP monthly change, reported in thousands; +-1000K spans even the
    # 2020 pandemic collapse/rebound prints.
    "NFP": (-1000.0, 1000.0),
    # Trade balance: sign-agnostic pass-through -- EUR/USD report low tens of
    # billions, JPY reports hundreds of billions yen. No single range is
    # meaningful; the IQR screen below is this category's only gate.
    "TRADEBAL": None,
    # Rate-decision series have 0 usable (forecast+actual) rows in the source
    # snapshot (see module docstring / verification report), so these never
    # actually reach the gate, but are listed for completeness rather than
    # falling through to an unconfigured-category warning.
    "ECB_RATE": None,
    "FED_RATE": None,
    "BOJ_RATE": None,
}

#: Below this many points in a (country, title) group, the outlier screen is
#: skipped -- three data points don't support a meaningful quartile estimate.
MIN_IQR_GROUP_SIZE = 4
#: Outlier bound width in units of IQR, centred on the group median.
IQR_K = 3.0


@dataclass(frozen=True)
class QuarantineEntry:
    """One row excluded from seeding, with the reason on record."""

    series_id: str
    release_date: str
    forecast_value: float | None
    actual_value: float | None
    reason: str
    detail: str


@dataclass(frozen=True)
class SeedResult:
    """Full accounting of one seeding run -- every input row lands somewhere."""

    total_usable: int
    unmapped: list[QuarantineEntry]
    range_quarantined: list[QuarantineEntry]
    iqr_quarantined: list[QuarantineEntry]
    iqr_skipped_groups: list[str]
    dedupe_skipped: list[QuarantineEntry]
    inserted: list[tuple[str, str, str, float, float, str]]
    committed: bool

    @property
    def quarantined(self) -> list[QuarantineEntry]:
        """All data-quality quarantines (unmapped + range + IQR), not dedupe."""
        return [*self.unmapped, *self.range_quarantined, *self.iqr_quarantined]


def _country_of(series_id: str) -> str:
    head, _, _ = series_id.partition(".")
    return head


def _category_of(series_id: str) -> str:
    _, _, tail = series_id.partition(".")
    return tail or series_id


def _classify_all(
    usable: list[CalendarRelease],
) -> tuple[list[Classified], list[QuarantineEntry]]:
    """Resolve each usable row to a ForexFactory title/vintage, or quarantine it."""
    classified: list[Classified] = []
    unmapped: list[QuarantineEntry] = []
    for row in usable:
        country = ctm.normalize_country(_country_of(row.series_id))
        release_date = date.fromisoformat(row.release_date)
        candidates = ctm.to_ff_titles(row.series_id, country)
        mapping = ctm.classify_release(row.series_id, country, release_date)
        if mapping is not None:
            classified.append((row, mapping))
            continue
        if not candidates:
            note = ctm.UNMAPPED_NOTES.get(
                (country, row.series_id), "no title mapping for this series_id"
            )
            detail = note
        else:
            cand_titles = ", ".join(c.ff_title for c in candidates)
            detail = (
                f"release_date {row.release_date} matches no vintage window "
                f"among candidates: {cand_titles}"
            )
        unmapped.append(
            QuarantineEntry(
                series_id=row.series_id,
                release_date=row.release_date,
                forecast_value=row.forecast_value,
                actual_value=row.actual_value,
                reason="unmapped",
                detail=detail,
            )
        )
    return classified, unmapped


def _range_gate(
    classified: list[Classified],
) -> tuple[list[Classified], list[QuarantineEntry]]:
    """Drop rows whose forecast/actual is outside the plausible range."""
    passed: list[Classified] = []
    quarantined: list[QuarantineEntry] = []
    warned_categories: set[str] = set()
    for row, mapping in classified:
        category = _category_of(row.series_id)
        if category not in PLAUSIBILITY_RANGES and category not in warned_categories:
            logger.warning(
                "no plausibility range configured for category %r "
                "(series %s) -- IQR screen only",
                category,
                row.series_id,
            )
            warned_categories.add(category)
        bounds = PLAUSIBILITY_RANGES.get(category)
        if bounds is not None:
            lo, hi = bounds
            bad: list[str] = []
            if row.forecast_value is not None and not (lo <= row.forecast_value <= hi):
                bad.append(f"forecast={row.forecast_value}")
            if row.actual_value is not None and not (lo <= row.actual_value <= hi):
                bad.append(f"actual={row.actual_value}")
            if bad:
                quarantined.append(
                    QuarantineEntry(
                        series_id=row.series_id,
                        release_date=row.release_date,
                        forecast_value=row.forecast_value,
                        actual_value=row.actual_value,
                        reason="range",
                        detail=(
                            f"{mapping.ff_title}: {', '.join(bad)} outside "
                            f"plausible [{lo}, {hi}]"
                        ),
                    )
                )
                continue
        passed.append((row, mapping))
    return passed, quarantined


def _iqr_gate(
    passed: list[Classified],
) -> tuple[list[Classified], list[QuarantineEntry], list[str]]:
    """Screen each (country, title) group's surprises for outliers.

    Flags rows whose ``actual - forecast`` falls outside
    ``median +/- IQR_K * IQR`` of its own group's surprise distribution.

    A group is skipped (passed through unscreened) when it has fewer than
    :data:`MIN_IQR_GROUP_SIZE` points, or when its IQR is exactly zero. The
    zero-IQR case matters more than it looks: several of these indicators
    report to one decimal place and frequently print exactly on consensus
    (e.g. euro-area Unemployment Rate: 6/10 releases in the source window
    have zero surprise), so the median/Q1/Q3 all collapse to 0 and a naive
    "median +/- 3*0" bound would flag *every* nonzero surprise as an
    outlier -- including perfectly ordinary +-0.1pp misses. Skipping the
    screen when IQR==0 avoids manufacturing false positives out of a
    tie-heavy distribution; those groups still went through the range gate.
    """
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, (row, mapping) in enumerate(passed):
        groups[(mapping.country, mapping.ff_title)].append(idx)

    keep = [True] * len(passed)
    quarantined: list[QuarantineEntry] = []
    skipped_groups: list[str] = []

    for (country, title), idxs in groups.items():
        if len(idxs) < MIN_IQR_GROUP_SIZE:
            skipped_groups.append(
                f"{country} {title} (n={len(idxs)} < MIN_IQR_GROUP_SIZE)"
            )
            continue
        surprises = [
            passed[i][0].actual_value - passed[i][0].forecast_value for i in idxs
        ]
        median = statistics.median(surprises)
        q1, _, q3 = statistics.quantiles(surprises, n=4, method="inclusive")
        iqr = q3 - q1
        if iqr == 0.0:
            skipped_groups.append(f"{country} {title} (n={len(idxs)}, IQR=0)")
            continue
        lo_bound, hi_bound = median - IQR_K * iqr, median + IQR_K * iqr
        for i, surprise in zip(idxs, surprises, strict=True):
            if lo_bound <= surprise <= hi_bound:
                continue
            keep[i] = False
            row, mapping = passed[i]
            quarantined.append(
                QuarantineEntry(
                    series_id=row.series_id,
                    release_date=row.release_date,
                    forecast_value=row.forecast_value,
                    actual_value=row.actual_value,
                    reason="iqr_outlier",
                    detail=(
                        f"{mapping.ff_title}: surprise={surprise:+.3f} outside "
                        f"median+/-{IQR_K:g}*IQR=[{lo_bound:+.3f}, {hi_bound:+.3f}] "
                        f"(median={median:+.3f}, IQR={iqr:.3f}, n={len(idxs)})"
                    ),
                )
            )

    kept = [passed[i] for i in range(len(passed)) if keep[i]]
    return kept, quarantined, skipped_groups


def _dedupe(
    store: MacroStore,
    kept: list[Classified],
) -> tuple[list[Classified], list[QuarantineEntry]]:
    """Drop rows already covered by an existing (country, title) event +/-1 day.

    Prevents double-counting the 2026-03-30-onward window where our organic
    ForexFactory JSON collector and the JBlanked backfill both have data.

    A collision only counts when the existing event actually carries a
    released actual: an organic row with ``is_released=0 / actual=NULL``
    contributes nothing to surprise history, so yielding a seed row (which
    has forecast+actual) to such an empty twin would silently lose usable
    surprise points (Advisor finding F-1).
    """
    to_insert: list[Classified] = []
    skipped: list[QuarantineEntry] = []
    existing_dates_cache: dict[tuple[str, str], list[date]] = {}

    for row, mapping in kept:
        key = (mapping.country, mapping.ff_title)
        if key not in existing_dates_cache:
            existing = store.query_events(
                country=mapping.country, title_exact=mapping.ff_title
            )
            existing_dates_cache[key] = [
                e.datetime_utc.date()
                for e in existing
                if e.is_released and e.actual is not None
            ]
        release_date = date.fromisoformat(row.release_date)
        collision = next(
            (
                d
                for d in existing_dates_cache[key]
                if abs((release_date - d).days) <= 1
            ),
            None,
        )
        if collision is not None:
            skipped.append(
                QuarantineEntry(
                    series_id=row.series_id,
                    release_date=row.release_date,
                    forecast_value=row.forecast_value,
                    actual_value=row.actual_value,
                    reason="dedupe",
                    detail=(
                        f"{mapping.country} {mapping.ff_title} already present "
                        f"at {collision.isoformat()} (within +/-1d)"
                    ),
                )
            )
            continue
        to_insert.append((row, mapping))
    return to_insert, skipped


def _build_event(row: CalendarRelease, mapping: ctm.FFTitleMapping) -> CalendarEvent:
    release_date = date.fromisoformat(row.release_date)
    # Source has no intraday release time; 00:00:00Z is a documented
    # placeholder (see module docstring). Section B excludes seed rows from
    # display, so this never surfaces as a release time to a reader.
    dt_utc = datetime(
        release_date.year, release_date.month, release_date.day, tzinfo=UTC
    )
    eid = event_id(mapping.country, mapping.ff_title, dt_utc)
    return CalendarEvent(
        event_id=eid,
        country=mapping.country,
        title=mapping.ff_title,
        impact=SEED_IMPACT,
        datetime_utc=dt_utc,
        forecast=row.forecast_value,
        previous=row.previous_value,
        actual=row.actual_value,
        is_released=True,
        source=SEED_SOURCE,
        raw_time=None,
        raw_date=row.release_date,
    )


def run(
    *,
    source_db: Path | None,
    target_db: Path,
    commit: bool,
) -> SeedResult:
    client = OptionsdeckSeriesClient(db_path=source_db)
    availability = client.available()
    if not availability:
        raise SystemExit(f"optionsdeck source DB unavailable: {availability.reason}")
    logger.info(
        "source snapshot: %s (latest calendar release %s)",
        availability.db_path,
        availability.latest_calendar_release,
    )

    releases = client.get_calendar_history()
    usable = [
        r
        for r in releases
        if r.forecast_value is not None and r.actual_value is not None
    ]
    client.close()
    logger.info(
        "usable rows (forecast+actual both present): %d / %d",
        len(usable),
        len(releases),
    )

    classified, unmapped = _classify_all(usable)
    passed_range, range_q = _range_gate(classified)
    passed_iqr, iqr_q, iqr_skipped = _iqr_gate(passed_range)

    store = MacroStore(target_db)
    to_insert, dedupe_q = _dedupe(store, passed_iqr)

    inserted: list[tuple[str, str, str, float, float, str]] = []
    seen_ids: set[str] = set()
    for row, mapping in to_insert:
        event = _build_event(row, mapping)
        if event.event_id in seen_ids:
            # Two source rows collapsed onto the same (country, title, date) --
            # defensive, not expected to trigger against the real snapshot.
            logger.warning(
                "in-batch event_id collision for %s %s %s -- skipping duplicate",
                mapping.country,
                mapping.ff_title,
                row.release_date,
            )
            continue
        seen_ids.add(event.event_id)
        inserted.append(
            (
                mapping.country,
                mapping.ff_title,
                row.release_date,
                row.forecast_value,
                row.actual_value,
                row.series_id,
            )
        )
        if commit:
            store.upsert_event(event)

    return SeedResult(
        total_usable=len(usable),
        unmapped=unmapped,
        range_quarantined=range_q,
        iqr_quarantined=iqr_q,
        iqr_skipped_groups=iqr_skipped,
        dedupe_skipped=dedupe_q,
        inserted=inserted,
        committed=commit,
    )


def _print_summary(result: SeedResult) -> None:
    print()
    print("=" * 72)
    print(f"seed_calendar_history: {'COMMIT' if result.committed else 'DRY RUN'}")
    print("=" * 72)
    print(f"total usable source rows (forecast+actual present): {result.total_usable}")
    print(f"  unmapped (skip):           {len(result.unmapped)}")
    print(f"  range-quarantined (skip):  {len(result.range_quarantined)}")
    print(f"  IQR-outlier (skip):        {len(result.iqr_quarantined)}")
    print(f"  dedupe-skipped:            {len(result.dedupe_skipped)}")
    print(f"  inserted:                  {len(result.inserted)}")
    print()

    def _print_entries(title: str, entries: list[QuarantineEntry]) -> None:
        if not entries:
            return
        print(f"-- {title} ({len(entries)}) --")
        for e in entries:
            print(f"  {e.series_id:16} {e.release_date}  {e.detail}")
        print()

    _print_entries("unmapped", result.unmapped)
    _print_entries("range-quarantined", result.range_quarantined)
    _print_entries("IQR-outlier-quarantined", result.iqr_quarantined)
    if result.iqr_skipped_groups:
        print(f"-- IQR screen skipped for {len(result.iqr_skipped_groups)} group(s) --")
        for g in result.iqr_skipped_groups:
            print(f"  {g}")
        print()
    _print_entries("dedupe-skipped", result.dedupe_skipped)

    if result.inserted:
        print(f"-- inserted ({len(result.inserted)}) --")
        for country, title, rel_date, forecast, actual, series_id in result.inserted:
            print(
                f"  {country:4} {title:32} {rel_date}  f={forecast} a={actual}  "
                f"(src={series_id})"
            )
        print()
    if not result.committed and result.inserted:
        print("(dry run -- no rows written; re-run with --commit to insert)")
        print()


def _print_stats(target_db: Path, before_str: str, min_history: int) -> None:
    from indepth_analysis.skills.euro_macro.macro_alerts import surprise_stats

    before_dt = datetime.fromisoformat(before_str)
    if before_dt.tzinfo is None:
        before_dt = before_dt.replace(tzinfo=UTC)
    store = MacroStore(target_db)

    full = surprise_stats(store, before=before_dt, min_history_points=1)
    qualifying = {k: v for k, v in full.items() if v.n >= min_history}

    print()
    print(
        f"=== surprise_stats snapshot: before={before_dt.isoformat()} "
        f"target_db={target_db} ==="
    )
    print(
        f"(country,title) groups with >=1 released surprise in the "
        f"24mo window: {len(full)}"
    )
    print(
        f"groups with n >= {min_history} (sigma-eligible, '*' below): "
        f"{len(qualifying)}"
    )
    print()
    print(f"{'':1} {'country':7} {'n':>3} {'mean':>9} {'sigma':>9}  title")
    for (country, title), stat in sorted(
        full.items(), key=lambda kv: (-kv[1].n, kv[0])
    ):
        flag = "*" if stat.n >= min_history else " "
        print(
            f"{flag} {country:7} {stat.n:>3} {stat.mean:>9.4f} "
            f"{stat.sigma:>9.4f}  {title}"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Seed calendar_events with JBlanked/faireconomy calendar history "
            "from the optionsdeck backbone, re-titled to ForexFactory's "
            "vocabulary. Default is a dry run; pass --commit to insert."
        )
    )
    parser.add_argument(
        "--source-db",
        type=Path,
        default=None,
        help=(
            "override the optionsdeck macro.db path (else OPTIONSDECK_MACRO_DB "
            "env var, else ~/.optionsdeck-gb/data/macro.db)"
        ),
    )
    parser.add_argument(
        "--target-db",
        type=Path,
        default=DEFAULT_TARGET_DB,
        help=f"bgilib MacroStore db to seed into (default: {DEFAULT_TARGET_DB})",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually insert rows (default: dry run, prints the plan only)",
    )
    parser.add_argument(
        "--stats-before",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "diagnostic mode: skip seeding, print the surprise_stats() "
            "snapshot of --target-db as of this date, and exit"
        ),
    )
    parser.add_argument(
        "--min-history",
        type=int,
        default=6,
        help=(
            "min_history_points threshold for the --stats-before "
            "'*' flag (default: 6)"
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.stats_before:
        _print_stats(args.target_db, args.stats_before, args.min_history)
        return 0

    result = run(source_db=args.source_db, target_db=args.target_db, commit=args.commit)
    _print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
