"""JBlanked/MQL5 generic title ↔ ForexFactory canonical title mapping.

Why this exists
---------------
Two calendar sources describe the same releases with different names, and
one of them collapses distinct release vintages into a single name:

===========================  =====================================
JBlanked / MQL5 generic      ForexFactory canonical
===========================  =====================================
``CPI y/y`` (EU)             ``CPI Flash Estimate y/y`` (month-end)
                             ``Final CPI y/y`` (mid next month)
``GDP q/q`` (EU)             ``Prelim Flash GDP q/q`` (Q+1 month)
                             ``Flash GDP q/q`` (Q+2 month)
``Nonfarm Payrolls`` (US)    ``Non-Farm Employment Change``
``ISM Non-Manufacturing      ``ISM Services PMI``
PMI`` (US)
===========================  =====================================

Seeding historical surprises into ``calendar_events`` therefore cannot be a
plain title copy. Two things have to happen first:

1. **rename** to the exact ForexFactory title — ``MacroStore`` looks
   indicator history up by exact title, so ``CPI y/y`` rows would form a
   pool nothing ever reads; and
2. **vintage split** — pooling the month-end flash with the mid-month final
   understates the flash's dispersion (the final almost never surprises),
   which inflates every flash z-score into a false alert.

The vintage a JBlanked row belongs to is recoverable from its
``release_date`` alone. Monthly indicators split on day-of-month (euro-area
HICP flash lands day 26-31 or 1-8, the final day 14-25); quarterly ones
split on how many months after the quarter end the release falls
(euro-area GDP: +1 month = Prelim Flash, +2 = Flash, +3 = Final).

Provenance
----------
Built by cross-reading two real tables, not from memory:

* generic side — ``macro_calendar_history`` in the optionsdeck snapshot
  (44 distinct ``(series_id, event_title)`` pairs, 294 rows carrying both a
  forecast and an actual);
* ForexFactory side — ``calendar_events.title`` in
  ``data/macro_calendar.db``.

``observed_in_ff_db`` records whether that exact ForexFactory title was
present in our calendar DB at build time (2026-08). ``False`` does not mean
the title is wrong — our DB only holds a few months of ``thisweek``
snapshots, so low-frequency and Low-impact events are simply absent — but a
seeding run that produces only ``observed_in_ff_db=False`` titles deserves a
second look.

Usage
-----
Look up every ForexFactory variant a generic series maps to::

    >>> from indepth_analysis.skills.euro_macro import calendar_title_map as ctm
    >>> [m.ff_title for m in ctm.to_ff_titles("EU.HICP_YOY", "EUR")]
    ['CPI Flash Estimate y/y', 'Final CPI y/y']
    >>> [m.ff_title for m in ctm.to_ff_titles("CPI y/y", "EUR")]
    ['CPI Flash Estimate y/y', 'Final CPI y/y']

Pick the one a concrete historical row belongs to::

    >>> from datetime import date
    >>> ctm.classify_release("EU.HICP_YOY", "EUR", date(2026, 4, 30)).ff_title
    'CPI Flash Estimate y/y'
    >>> ctm.classify_release("EU.HICP_YOY", "EUR", date(2026, 4, 16)).ff_title
    'Final CPI y/y'

Unmapped input yields an empty list / ``None`` — the seeding script skips
those rows and reports them rather than guessing::

    >>> ctm.to_ff_titles("JP.CPI_YOY", "JPY")
    []
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "MAPPINGS",
    "UNMAPPED_NOTES",
    "FFTitleMapping",
    "ReleaseWindow",
    "classify_release",
    "from_ff_title",
    "known_keys",
    "normalize_country",
    "to_ff_titles",
]

# JBlanked series-id prefix -> ForexFactory country code.
_COUNTRY_ALIASES = {
    "EU": "EUR",
    "EA": "EUR",
    "US": "USD",
    "JP": "JPY",
    "GB": "GBP",
    "UK": "GBP",
    "CN": "CNY",
    "CH": "CHF",
    "SE": "SEK",
    "KR": "KRW",
}


def normalize_country(country: str | None) -> str:
    """Map a JBlanked country prefix to the ForexFactory currency code.

    ``"EU"`` -> ``"EUR"``, ``"US"`` -> ``"USD"``; already-canonical codes
    pass through unchanged.
    """
    if not country:
        return ""
    code = country.strip().upper()
    return _COUNTRY_ALIASES.get(code, code)


@dataclass(frozen=True)
class ReleaseWindow:
    """Which release dates belong to one ForexFactory vintage.

    Args:
        days: Inclusive day-of-month ranges. Empty means "any day".
            Month-end windows wrap, e.g. ``((26, 31), (1, 8))``.
        month_offsets: For quarterly indicators, allowed month offsets after
            the reference quarter end (1, 2 or 3). Empty means "any month".

    A date matches only when *every* non-empty constraint accepts it.
    """

    days: tuple[tuple[int, int], ...] = ()
    month_offsets: tuple[int, ...] = ()

    def contains(self, release_date: date) -> bool:
        if self.days and not any(lo <= release_date.day <= hi for lo, hi in self.days):
            return False
        if self.month_offsets:
            # Months elapsed since the most recent quarter end (Mar/Jun/Sep/Dec):
            # Jan/Apr/Jul/Oct -> 1, Feb/May/Aug/Nov -> 2, Mar/Jun/Sep/Dec -> 3.
            offset = ((release_date.month - 1) % 3) + 1
            if offset not in self.month_offsets:
                return False
        return True


#: Matches any release date — used by single-vintage indicators.
ANY_WINDOW = ReleaseWindow()

# Reusable day windows (verified against real release dates).
_MONTH_TURN = ((26, 31), (1, 8))  # euro-area HICP flash, unemployment rate
_MID_MONTH = ((14, 25),)  # euro-area HICP final, trade balance
_PMI_FLASH = ((18, 26),)  # S&P Global flash PMI
_PMI_FINAL = ((1, 8),)  # S&P Global final PMI


@dataclass(frozen=True)
class FFTitleMapping:
    """One (generic series, vintage) -> ForexFactory title mapping.

    Args:
        series_id: JBlanked/optionsdeck series id, e.g. ``"EU.HICP_YOY"``.
        generic_title: Title as the generic feed writes it.
        country: ForexFactory country code, e.g. ``"EUR"``.
        ff_title: Exact ForexFactory title to seed under. ``MacroStore``
            matches titles exactly, so this string must be verbatim.
        release_kind: ``flash`` / ``final`` / ``prelim`` / ``revised`` /
            ``single``.
        window: Release-date window that identifies this vintage.
        observed_in_ff_db: The title was seen in ``data/macro_calendar.db``
            when this table was built.
        note: Free-text provenance / caveat.
        aliases: Extra generic titles that resolve to the same mapping.
    """

    series_id: str
    generic_title: str
    country: str
    ff_title: str
    release_kind: str
    window: ReleaseWindow = ANY_WINDOW
    observed_in_ff_db: bool = False
    note: str = ""
    aliases: tuple[str, ...] = field(default=())

    @property
    def is_split(self) -> bool:
        """True when this mapping is one of several vintages for a series."""
        return self.release_kind != "single"


MAPPINGS: tuple[FFTitleMapping, ...] = (
    # ---------------- Euro area ----------------------------------------
    FFTitleMapping(
        "EU.HICP_YOY",
        "CPI y/y",
        "EUR",
        "CPI Flash Estimate y/y",
        "flash",
        ReleaseWindow(days=_MONTH_TURN),
        observed_in_ff_db=True,
        note="Eurostat flash HICP, last working day of the reference month",
        aliases=("CPI Flash Estimate y/y",),
    ),
    FFTitleMapping(
        "EU.HICP_YOY",
        "CPI y/y",
        "EUR",
        "Final CPI y/y",
        "final",
        ReleaseWindow(days=_MID_MONTH),
        note="Eurostat final HICP, mid of the following month",
    ),
    FFTitleMapping(
        "EU.CORE_CPI_YOY",
        "Core CPI y/y",
        "EUR",
        "Core CPI Flash Estimate y/y",
        "flash",
        ReleaseWindow(days=_MONTH_TURN),
        observed_in_ff_db=True,
        note="released alongside the headline flash",
        aliases=("Core CPI Flash Estimate y/y",),
    ),
    FFTitleMapping(
        "EU.CORE_CPI_YOY",
        "Core CPI y/y",
        "EUR",
        "Final Core CPI y/y",
        "final",
        ReleaseWindow(days=_MID_MONTH),
        note="released alongside the headline final",
    ),
    FFTitleMapping(
        "EU.GDP_QOQ",
        "GDP q/q",
        "EUR",
        "Prelim Flash GDP q/q",
        "flash",
        ReleaseWindow(month_offsets=(1,)),
        observed_in_ff_db=True,
        note="~30 days after quarter end",
        aliases=("Prelim Flash GDP q/q",),
    ),
    FFTitleMapping(
        "EU.GDP_QOQ",
        "GDP q/q",
        "EUR",
        "Flash GDP q/q",
        "flash2",
        ReleaseWindow(month_offsets=(2,)),
        note="second estimate, ~day 14 of the second month after quarter end",
    ),
    FFTitleMapping(
        "EU.GDP_QOQ",
        "GDP q/q",
        "EUR",
        "Final GDP q/q",
        "final",
        ReleaseWindow(month_offsets=(3,)),
        note="third estimate, early in the third month after quarter end",
    ),
    FFTitleMapping(
        "EU.PMI_MFG",
        "S&P Global Manufacturing PMI",
        "EUR",
        "Flash Manufacturing PMI",
        "flash",
        ReleaseWindow(days=_PMI_FLASH),
        note="S&P Global flash, ~day 20-24 of the reference month",
    ),
    FFTitleMapping(
        "EU.PMI_MFG",
        "S&P Global Manufacturing PMI",
        "EUR",
        "Final Manufacturing PMI",
        "final",
        ReleaseWindow(days=_PMI_FINAL),
        observed_in_ff_db=True,
        note="S&P Global final, first business days of the following month",
    ),
    FFTitleMapping(
        "EU.PMI_SVC",
        "S&P Global Services PMI",
        "EUR",
        "Flash Services PMI",
        "flash",
        ReleaseWindow(days=_PMI_FLASH),
        note="released with the flash manufacturing print",
    ),
    FFTitleMapping(
        "EU.PMI_SVC",
        "S&P Global Services PMI",
        "EUR",
        "Final Services PMI",
        "final",
        ReleaseWindow(days=_PMI_FINAL),
        observed_in_ff_db=True,
        note="released with the final manufacturing print",
    ),
    FFTitleMapping(
        "EU.UNRATE",
        "Unemployment Rate",
        "EUR",
        "Unemployment Rate",
        "single",
        ReleaseWindow(days=_MONTH_TURN),
        observed_in_ff_db=True,
        note="Eurostat harmonised rate, released with the HICP flash",
    ),
    FFTitleMapping(
        "EU.TRADEBAL",
        "Trade Balance",
        "EUR",
        "Trade Balance",
        "single",
        ReleaseWindow(days=((13, 22),)),
        note="euro-area goods balance, mid-month; not seen in our FF snapshot",
    ),
    FFTitleMapping(
        "EU.RETAIL_MM",
        "Retail Sales m/m",
        "EUR",
        "Retail Sales m/m",
        "single",
        ReleaseWindow(days=((1, 12),)),
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "EU.ECB_RATE",
        "ECB Interest Rate Decision",
        "EUR",
        "Main Refinancing Rate",
        "single",
        observed_in_ff_db=True,
        note=(
            "ForexFactory splits the ECB decision into Main Refinancing Rate "
            "+ Monetary Policy Statement + Press Conference; the rate row is "
            "the numeric one"
        ),
        aliases=("Main Refinancing Rate",),
    ),
    # ---------------- United States -------------------------------------
    FFTitleMapping(
        "US.NFP",
        "Nonfarm Payrolls",
        "USD",
        "Non-Farm Employment Change",
        "single",
        observed_in_ff_db=True,
        note="MQL5 uses the BLS name, ForexFactory the change wording",
    ),
    FFTitleMapping(
        "US.UNRATE",
        "Unemployment Rate",
        "USD",
        "Unemployment Rate",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "US.CPI_YOY", "CPI y/y", "USD", "CPI y/y", "single", observed_in_ff_db=True
    ),
    FFTitleMapping(
        "US.CPI_MM", "CPI m/m", "USD", "CPI m/m", "single", observed_in_ff_db=True
    ),
    FFTitleMapping(
        "US.CORECPI_YOY",
        "Core CPI y/y",
        "USD",
        "Core CPI y/y",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "US.CORECPI_MM",
        "Core CPI m/m",
        "USD",
        "Core CPI m/m",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "US.PPI_MM", "PPI m/m", "USD", "PPI m/m", "single", observed_in_ff_db=True
    ),
    FFTitleMapping(
        "US.PPI_YOY",
        "PPI y/y",
        "USD",
        "PPI y/y",
        "single",
        note="ForexFactory leads with PPI m/m; the y/y row is Low impact",
    ),
    FFTitleMapping(
        "US.CORE_PCE_MM",
        "Core PCE Price Index m/m",
        "USD",
        "Core PCE Price Index m/m",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "US.RETAIL_MM", "Retail Sales m/m", "USD", "Retail Sales m/m", "single"
    ),
    FFTitleMapping(
        "US.CORE_RETAIL_MM",
        "Core Retail Sales m/m",
        "USD",
        "Core Retail Sales m/m",
        "single",
    ),
    FFTitleMapping(
        "US.ISM_MFG",
        "ISM Manufacturing PMI",
        "USD",
        "ISM Manufacturing PMI",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "US.ISM_SVC",
        "ISM Non-Manufacturing PMI",
        "USD",
        "ISM Services PMI",
        "single",
        observed_in_ff_db=True,
        note="ForexFactory renamed the non-manufacturing index to Services",
    ),
    FFTitleMapping(
        "US.JOLTS",
        "JOLTS Job Openings",
        "USD",
        "JOLTS Job Openings",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "US.TRADEBAL", "Trade Balance", "USD", "Trade Balance", "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "US.GDP_QOQ",
        "GDP q/q",
        "USD",
        "Advance GDP q/q",
        "flash",
        ReleaseWindow(month_offsets=(1,)),
        observed_in_ff_db=True,
        note="BEA advance estimate, month after quarter end",
        aliases=("Advance GDP q/q",),
    ),
    FFTitleMapping(
        "US.GDP_QOQ",
        "GDP q/q",
        "USD",
        "Prelim GDP q/q",
        "prelim",
        ReleaseWindow(month_offsets=(2,)),
        note="BEA second estimate",
    ),
    FFTitleMapping(
        "US.GDP_QOQ",
        "GDP q/q",
        "USD",
        "Final GDP q/q",
        "final",
        ReleaseWindow(month_offsets=(3,)),
        note="BEA third estimate",
    ),
    FFTitleMapping(
        "US.FED_RATE",
        "Fed Interest Rate Decision",
        "USD",
        "Federal Funds Rate",
        "single",
        observed_in_ff_db=True,
        aliases=("Federal Funds Rate",),
    ),
    # ---------------- Japan ---------------------------------------------
    FFTitleMapping(
        "JP.UNRATE",
        "Unemployment Rate",
        "JPY",
        "Unemployment Rate",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "JP.TOKYO_CORECPI",
        "Tokyo Core CPI y/y",
        "JPY",
        "Tokyo Core CPI y/y",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "JP.CORECPI_YOY",
        "Core CPI y/y",
        "JPY",
        "National Core CPI y/y",
        "single",
        note="ForexFactory prefixes the nationwide print with 'National'",
    ),
    FFTitleMapping(
        "JP.RETAIL_YOY",
        "Retail Sales y/y",
        "JPY",
        "Retail Sales y/y",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "JP.TRADEBAL",
        "Trade Balance",
        "JPY",
        "Trade Balance",
        "single",
        note="not seen in our FF snapshot window",
    ),
    FFTitleMapping(
        "JP.INDPRO_MM",
        "Industrial Production m/m",
        "JPY",
        "Prelim Industrial Production m/m",
        "prelim",
        ReleaseWindow(days=((26, 31), (1, 5))),
        observed_in_ff_db=True,
        aliases=("Prelim Industrial Production m/m",),
    ),
    FFTitleMapping(
        "JP.INDPRO_MM",
        "Industrial Production m/m",
        "JPY",
        "Revised Industrial Production m/m",
        "revised",
        ReleaseWindow(days=((10, 20),)),
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "JP.GDP_QOQ",
        "GDP q/q",
        "JPY",
        "Prelim GDP q/q",
        "prelim",
        ReleaseWindow(month_offsets=(2,)),
        note="Cabinet Office first preliminary, ~day 15",
    ),
    FFTitleMapping(
        "JP.GDP_QOQ",
        "GDP q/q",
        "JPY",
        "Final GDP q/q",
        "final",
        ReleaseWindow(month_offsets=(3,)),
        observed_in_ff_db=True,
        note="Cabinet Office second preliminary, ~day 8",
    ),
    FFTitleMapping(
        "JP.TANKAN_MFG",
        "BoJ Tankan Large Manufacturing Index",
        "JPY",
        "Tankan Manufacturing Index",
        "single",
        observed_in_ff_db=True,
    ),
    FFTitleMapping(
        "JP.BOJ_RATE",
        "BoJ Interest Rate Decision",
        "JPY",
        "BOJ Policy Rate",
        "single",
        observed_in_ff_db=True,
        aliases=("BOJ Policy Rate",),
    ),
)

# Deliberately unmapped, with the reason — the seeding script reports these
# rather than guessing a ForexFactory title that may not exist:
#   JP.CPI_YOY 'CPI y/y'       — ForexFactory tracks the national CORE print,
#                                not a bare nationwide headline y/y row.
#   JP.RETAIL_MM 'Retail Sales m/m' — ForexFactory carries the y/y variant only.
UNMAPPED_NOTES: dict[tuple[str, str], str] = {
    ("JPY", "JP.CPI_YOY"): (
        "ForexFactory tracks 'National Core CPI y/y', not a bare headline row"
    ),
    ("JPY", "JP.RETAIL_MM"): "ForexFactory carries Retail Sales y/y only",
}


def _build_index() -> dict[tuple[str, str], list[FFTitleMapping]]:
    index: dict[tuple[str, str], list[FFTitleMapping]] = {}
    for mapping in MAPPINGS:
        keys = {
            mapping.series_id.lower(),
            mapping.generic_title.lower(),
            mapping.ff_title.lower(),
            *(a.lower() for a in mapping.aliases),
        }
        for key in keys:
            index.setdefault((mapping.country, key), []).append(mapping)
    return index


_INDEX = _build_index()


def to_ff_titles(
    series_id_or_generic_title: str, country: str | None = None
) -> list[FFTitleMapping]:
    """Return every ForexFactory variant for a generic series or title.

    Args:
        series_id_or_generic_title: ``"EU.HICP_YOY"``, ``"CPI y/y"`` or an
            already-canonical ForexFactory title (identity round-trip).
        country: ForexFactory code (``"EUR"``) or JBlanked prefix
            (``"EU"``). When omitted it is inferred from a dotted series id.

    Returns:
        Mappings in release order (flash before final), or an empty list
        when nothing matches — callers should skip and report, never guess.
    """
    key = (series_id_or_generic_title or "").strip()
    if not key:
        return []
    code = normalize_country(country)
    if not code and "." in key:
        code = normalize_country(key.split(".", 1)[0])
    return list(_INDEX.get((code, key.lower()), []))


def from_ff_title(ff_title: str, country: str | None = None) -> list[FFTitleMapping]:
    """Reverse lookup: ForexFactory title -> mapping(s) carrying the series id."""
    code = normalize_country(country)
    lowered = (ff_title or "").strip().lower()
    return [
        m
        for m in MAPPINGS
        if m.ff_title.lower() == lowered and (not code or m.country == code)
    ]


def classify_release(
    series_id_or_generic_title: str,
    country: str | None,
    release_date: date,
) -> FFTitleMapping | None:
    """Return the vintage a historical row belongs to, or ``None``.

    A single-vintage series matches unconditionally. A split series matches
    the first variant whose :class:`ReleaseWindow` accepts ``release_date``;
    a date that falls in no window returns ``None`` so the seeding script can
    quarantine the row instead of assigning it to the wrong pool.
    """
    candidates = to_ff_titles(series_id_or_generic_title, country)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0] if candidates[0].window.contains(release_date) else None
    for mapping in candidates:
        if mapping.window.contains(release_date):
            return mapping
    return None


def known_keys() -> list[tuple[str, str]]:
    """Return sorted ``(country, series_id)`` pairs the table covers."""
    return sorted({(m.country, m.series_id) for m in MAPPINGS})
