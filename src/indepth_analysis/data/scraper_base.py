from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class ScraperResult(BaseModel):
    """Metadata for a single report discovered by a scraper."""

    external_id: str
    title: str
    category: str = ""
    author: str = ""
    published_date: str | None = None
    url: str
    file_url: str | None = None


class BaseScraper(Protocol):
    """Protocol for report source scrapers."""

    source_name: str
    base_url: str

    def scrape_listing(
        self,
        year: int | None = None,
        month: int | None = None,
        limit: int | None = None,
    ) -> list[ScraperResult]:
        """Scrape report metadata from listing pages."""
        ...

    def download_file(self, result: ScraperResult, dest_dir: Path) -> Path | None:
        """Download report file. Returns local path or None if restricted."""
        ...
