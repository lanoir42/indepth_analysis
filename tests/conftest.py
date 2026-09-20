"""Shared test fixtures for indepth_analysis tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to a temporary SQLite database."""
    return tmp_path / "test.db"


@pytest.fixture(autouse=True)
def report_transport_disabled_by_default(monkeypatch):
    # Runtime enable marker must not make legacy mocked tests invoke a real CLI.
    monkeypatch.setenv('INDEPTH_REPORT_FALLBACK', '0')
