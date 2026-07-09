"""Tests for Notion page-id extraction (regression: slug-char merge bug)."""

import pytest

from indepth_analysis.output.notion_publisher import _extract_page_id


def test_url_with_slug_prefix():
    # The "2" in "2026-H2-" must NOT merge into the id.
    url = "https://app.notion.com/p/2026-H2-397294e2c0788108bf5ae3abbcf62fd1"
    assert _extract_page_id(url) == "397294e2-c078-8108-bf5a-e3abbcf62fd1"


def test_raw_undashed_id():
    assert (
        _extract_page_id("397294e2c0788108bf5ae3abbcf62fd1")
        == "397294e2-c078-8108-bf5a-e3abbcf62fd1"
    )


def test_url_with_query_and_trailing_slash():
    url = "https://notion.so/My-Page-397294e2c0788108bf5ae3abbcf62fd1/?pvs=4"
    assert _extract_page_id(url) == "397294e2-c078-8108-bf5a-e3abbcf62fd1"


def test_no_id_raises():
    with pytest.raises(ValueError):
        _extract_page_id("https://app.notion.com/p/no-id-here")
