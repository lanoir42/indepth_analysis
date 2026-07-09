"""Tests for the forecast comparison-table renderer (network-free)."""

from indepth_analysis.skills.euro_macro import forecast_tables as ft


def _sample() -> dict:
    return {
        "meta": {
            "title": "기관별 전망 비교",
            "as_of": "2026-07-09",
            "region": "유로존(EA20)",
            "vintage_prior_label": "지난 연말 (2025-11/12)",
            "vintage_latest_label": "최근 (2026-04~07)",
            "rate_prior_label": "B-1. 지난 연말 시점",
            "rate_latest_label": "B-2. 2026-06 시점",
        },
        "gdp_2026": [
            {
                "institution": "IMF",
                "group": "공식기관",
                "prior": {
                    "value": 1.2,
                    "date": "2025-10-14",
                    "source": "IMF WEO Oct 2025",
                    "url": "https://imf.org/weo-oct2025",
                },
                "latest": {
                    "value": 0.9,
                    "date": "2026-04-16",
                    "source": "IMF WEO Apr 2026",
                    "url": "https://imf.org/weo-apr2026",
                },
            },
            {
                "institution": "Goldman Sachs",
                "group": "IB",
                "prior": None,
                "latest": {
                    "value": 1.0,
                    "date": "2026-06-02",
                    "source": "Reuters",
                    "url": "https://reuters.com/x",
                },
            },
        ],
        "inflation_2026": [],
        "rate_dfr": [
            {
                "institution": "Reuters 컨센서스",
                "group": "컨센서스",
                "prior": {
                    "26Q3": 1.75,
                    "26Q4": 1.75,
                    "27H1": 2.0,
                    "27H2": 2.0,
                    "date": "2025-12-18",
                    "source": "Reuters poll",
                    "url": "https://reuters.com/poll-dec2025",
                },
                "latest": {
                    "26Q3": 2.25,
                    "26Q4": 2.25,
                    "27H1": 2.5,
                    "27H2": None,
                    "date": "2026-06-20",
                    "source": "Reuters poll",
                    "url": "https://reuters.com/poll-jun2026",
                },
            },
        ],
        "notes": "테스트 주석.",
    }


def test_val_cell_and_delta():
    assert ft._val_cell({"value": 1.2, "date": "2025-10-14"}) == "1.2% (25-10)"
    assert ft._val_cell(None) == "미확인"
    assert ft._val_cell({"value": None}) == "미확인"
    assert ft._delta_cell({"value": 1.2}, {"value": 0.9}) == "-0.3%p"
    assert ft._delta_cell(None, {"value": 0.9}) == "—"


def test_rate_cell_missing_is_unverified():
    rate = {"26Q3": 2.25, "26Q4": None}
    assert ft._rate_cell(rate, "26Q3") == "2.25%"
    assert ft._rate_cell(rate, "26Q4") == "미확인"
    assert ft._rate_cell(None, "26Q3") == "미확인"


def test_metric_table_renders_unverified():
    data = _sample()
    tbl = ft.render_metric_table(data["gdp_2026"], data["meta"])
    assert "IMF" in tbl and "1.2% (25-10)" in tbl and "0.9% (26-04)" in tbl
    assert "-0.3%p" in tbl
    # Goldman prior is None -> 미확인
    assert "미확인" in tbl
    assert tbl.count("\n") >= 3  # header + sep + 2 rows


def test_rate_table_columns():
    data = _sample()
    tbl = ft.render_rate_table(data["rate_dfr"], "latest", "B-2")
    assert "26Q3" in tbl and "27H2" in tbl
    assert "2.25%" in tbl
    assert "미확인" in tbl  # 27H2 latest is None


def test_appendix_has_sections_and_sources():
    md = ft.render_forecast_appendix(_sample())
    assert "## A-1." in md  # GDP
    assert "## B." in md  # rate
    assert "## 출처 목록" in md
    assert "https://imf.org/weo-apr2026" in md
    assert "방법론" in md
    # no bullet lists or code fences (Notion-safe)
    assert "\n- " not in md and "```" not in md


def test_validate_flags_empty():
    problems = ft.validate({"meta": {}})
    assert problems == ["표 데이터(gdp_2026/inflation_2026/rate_dfr) 전무"]
    assert ft.validate(_sample()) == []
