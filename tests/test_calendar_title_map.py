"""Tests for the JBlanked/MQL5 <-> ForexFactory title mapping table."""

from __future__ import annotations

from datetime import date

from indepth_analysis.skills.euro_macro.calendar_title_map import (
    MAPPINGS,
    ReleaseWindow,
    classify_release,
    from_ff_title,
    known_keys,
    normalize_country,
    to_ff_titles,
)

# ---- country normalisation -------------------------------------------


def test_normalize_country_maps_jblanked_prefixes() -> None:
    assert normalize_country("EU") == "EUR"
    assert normalize_country("US") == "USD"
    assert normalize_country("JP") == "JPY"
    assert normalize_country("EUR") == "EUR"
    assert normalize_country(None) == ""


# ---- round trips -----------------------------------------------------


def test_round_trip_eur_hicp_flash() -> None:
    """Generic 'CPI y/y' -> FF flash title -> back to the series id."""
    mappings = to_ff_titles("CPI y/y", "EUR")
    flash = next(m for m in mappings if m.release_kind == "flash")
    assert flash.ff_title == "CPI Flash Estimate y/y"
    assert [m.series_id for m in from_ff_title(flash.ff_title, "EUR")] == [
        "EU.HICP_YOY"
    ]


def test_round_trip_us_nfp_rename() -> None:
    """MQL5 'Nonfarm Payrolls' is ForexFactory 'Non-Farm Employment Change'."""
    mappings = to_ff_titles("Nonfarm Payrolls", "USD")
    assert [m.ff_title for m in mappings] == ["Non-Farm Employment Change"]
    assert from_ff_title("Non-Farm Employment Change", "USD")[0].series_id == "US.NFP"


def test_round_trip_ism_services_rename() -> None:
    """'ISM Non-Manufacturing PMI' became 'ISM Services PMI' on ForexFactory."""
    mappings = to_ff_titles("US.ISM_SVC", "USD")
    assert [m.ff_title for m in mappings] == ["ISM Services PMI"]
    assert from_ff_title("ISM Services PMI")[0].generic_title == (
        "ISM Non-Manufacturing PMI"
    )


def test_round_trip_by_series_id_and_generic_title_agree() -> None:
    by_id = to_ff_titles("EU.PMI_MFG", "EUR")
    by_title = to_ff_titles("S&P Global Manufacturing PMI", "EU")
    assert [m.ff_title for m in by_id] == [m.ff_title for m in by_title]
    assert [m.ff_title for m in by_id] == [
        "Flash Manufacturing PMI",
        "Final Manufacturing PMI",
    ]


def test_ff_title_is_accepted_as_input_identity() -> None:
    """Feeding an already-canonical FF title back in resolves the same row."""
    mappings = to_ff_titles("Prelim Flash GDP q/q", "EUR")
    assert any(m.ff_title == "Prelim Flash GDP q/q" for m in mappings)


def test_country_can_be_inferred_from_dotted_series_id() -> None:
    assert to_ff_titles("US.UNRATE")[0].country == "USD"


# ---- flash / final split ---------------------------------------------


def test_hicp_flash_vs_final_split_by_day_of_month() -> None:
    """Month-end print is the flash; the mid-month print is the final."""
    flash = classify_release("EU.HICP_YOY", "EUR", date(2026, 4, 30))
    final = classify_release("EU.HICP_YOY", "EUR", date(2026, 4, 16))
    assert flash is not None and final is not None
    assert flash.ff_title == "CPI Flash Estimate y/y"
    assert final.ff_title == "Final CPI y/y"
    # Early-month prints (holiday shifts) still count as the flash.
    early = classify_release("EU.HICP_YOY", "EUR", date(2026, 1, 7))
    assert early is not None and early.release_kind == "flash"


def test_gdp_split_by_month_after_quarter_end() -> None:
    """Euro-area GDP vintages differ by month offset, not day."""
    prelim_flash = classify_release("EU.GDP_QOQ", "EUR", date(2025, 7, 30))
    second = classify_release("EU.GDP_QOQ", "EUR", date(2025, 8, 14))
    assert prelim_flash is not None and second is not None
    assert prelim_flash.ff_title == "Prelim Flash GDP q/q"
    assert second.ff_title == "Flash GDP q/q"


def test_pmi_flash_and_final_do_not_collide() -> None:
    flash = classify_release("EU.PMI_SVC", "EUR", date(2026, 3, 24))
    final = classify_release("EU.PMI_SVC", "EUR", date(2026, 4, 3))
    assert flash is not None and final is not None
    assert flash.ff_title == "Flash Services PMI"
    assert final.ff_title == "Final Services PMI"


def test_release_window_wraps_around_month_end() -> None:
    window = ReleaseWindow(days=((26, 31), (1, 8)))
    assert window.contains(date(2026, 4, 30))
    assert window.contains(date(2026, 5, 1))
    assert not window.contains(date(2026, 5, 15))


def test_release_window_month_offset_arithmetic() -> None:
    window = ReleaseWindow(month_offsets=(1,))
    for month in (1, 4, 7, 10):  # first month after each quarter end
        assert window.contains(date(2026, month, 15))
    for month in (2, 3, 5, 6):
        assert not window.contains(date(2026, month, 15))


# ---- refusal ---------------------------------------------------------


def test_unmapped_series_returns_empty_list() -> None:
    """Unknown input is skipped and reported, never guessed."""
    assert to_ff_titles("JP.CPI_YOY", "JPY") == []
    assert to_ff_titles("XX.MADE_UP", "EUR") == []
    assert classify_release("JP.CPI_YOY", "JPY", date(2026, 4, 24)) is None


def test_wrong_country_does_not_match() -> None:
    assert to_ff_titles("EU.HICP_YOY", "USD") == []


def test_date_outside_every_window_is_refused() -> None:
    """A date matching no vintage yields None so the row can be quarantined."""
    assert classify_release("EU.HICP_YOY", "EUR", date(2026, 4, 11)) is None


# ---- table integrity -------------------------------------------------


def test_ff_titles_within_a_series_are_unique() -> None:
    seen: set[tuple[str, str]] = set()
    for mapping in MAPPINGS:
        key = (mapping.country, mapping.ff_title)
        assert key not in seen, key
        seen.add(key)


def test_split_series_have_disjoint_windows() -> None:
    """No release date may resolve to two vintages of the same series."""
    by_series: dict[tuple[str, str], list] = {}
    for mapping in MAPPINGS:
        by_series.setdefault((mapping.country, mapping.series_id), []).append(mapping)
    for (country, series_id), group in by_series.items():
        if len(group) < 2:
            continue
        for year in (2025, 2026):
            for month in range(1, 13):
                for day in (1, 4, 8, 14, 20, 24, 28):
                    day_ = date(year, month, day)
                    hits = [m for m in group if m.window.contains(day_)]
                    assert len(hits) <= 1, (country, series_id, day_, hits)


def test_known_keys_cover_the_euro_core() -> None:
    keys = set(known_keys())
    for series_id in ("EU.HICP_YOY", "EU.CORE_CPI_YOY", "EU.UNRATE", "EU.GDP_QOQ"):
        assert ("EUR", series_id) in keys
