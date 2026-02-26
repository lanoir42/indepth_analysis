import hashlib
import logging
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from indepth_analysis.data.scraper_base import ScraperResult

logger = logging.getLogger(__name__)

KCIF_BASE_URL = "https://www.kcif.or.kr"
KCIF_LIST_URL = f"{KCIF_BASE_URL}/front/board/boardList.do"
KCIF_VIEW_URL = f"{KCIF_BASE_URL}/front/board/boardView.do"

# KCIF board IDs for different report categories
BOARD_IDS = {
    "focus": "3",  # KCIF Focus (주요 분석 보고서)
    "weekly": "5",  # Weekly (주간 보고서)
    "daily": "4",  # Daily (일일 보고서)
    "special": "6",  # Special (특별 보고서)
}

DEFAULT_TIMEOUT = 30.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


class KCIFScraper:
    """Scraper for KCIF (Korea Center for International Finance) reports."""

    source_name: str = "KCIF"
    base_url: str = KCIF_BASE_URL

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        board_ids: list[str] | None = None,
    ) -> None:
        self._timeout = timeout
        self._board_ids = board_ids or list(BOARD_IDS.values())
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def scrape_listing(
        self,
        year: int | None = None,
        month: int | None = None,
        limit: int | None = None,
    ) -> list[ScraperResult]:
        """Scrape report metadata from KCIF listing pages."""
        all_results: list[ScraperResult] = []

        for board_id in self._board_ids:
            try:
                results = self._scrape_board(
                    board_id, year=year, month=month, limit=limit
                )
                all_results.extend(results)
                logger.info("Scraped %d results from board %s", len(results), board_id)
            except Exception:
                logger.warning("Failed to scrape board %s", board_id, exc_info=True)

            if limit and len(all_results) >= limit:
                all_results = all_results[:limit]
                break

        return all_results

    def _scrape_board(
        self,
        board_id: str,
        year: int | None = None,
        month: int | None = None,
        limit: int | None = None,
        max_pages: int = 10,
    ) -> list[ScraperResult]:
        results: list[ScraperResult] = []
        category = next((k for k, v in BOARD_IDS.items() if v == board_id), board_id)

        for page in range(1, max_pages + 1):
            params: dict[str, str | int] = {
                "boardId": board_id,
                "page": page,
            }
            if year:
                params["searchYear"] = year
            if month:
                params["searchMonth"] = f"{month:02d}"

            try:
                resp = self.client.get(KCIF_LIST_URL, params=params)
                resp.raise_for_status()
            except httpx.HTTPError:
                logger.warning(
                    "HTTP error fetching board %s page %d",
                    board_id,
                    page,
                    exc_info=True,
                )
                break

            page_results = self._parse_listing_page(resp.text, category)
            if not page_results:
                break

            results.extend(page_results)

            if limit and len(results) >= limit:
                results = results[:limit]
                break

        return results

    def _parse_listing_page(self, html: str, category: str) -> list[ScraperResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[ScraperResult] = []

        # Look for typical board list table rows
        rows = soup.select("table tbody tr")
        if not rows:
            # Try alternative: div-based listing
            rows = soup.select(".board-list li, .bbs-list li, .list-item")

        for row in rows:
            try:
                result = self._parse_row(row, category)
                if result:
                    results.append(result)
            except Exception:
                logger.debug("Failed to parse row", exc_info=True)
                continue

        return results

    def _parse_row(self, row: BeautifulSoup, category: str) -> ScraperResult | None:
        # Find the link element
        link = row.select_one("a[href]")
        if not link:
            return None

        title = link.get_text(strip=True)
        if not title:
            return None

        href = link.get("href", "")

        # Extract board content ID from href
        content_id = self._extract_content_id(str(href))
        if not content_id:
            return None

        # Build view URL
        bid = self._extract_board_id(str(href))
        url = f"{KCIF_VIEW_URL}?boardId={bid}&contentId={content_id}"

        # Extract date
        date_text = self._extract_date(row)

        # Extract author
        author = ""
        author_el = row.select_one(".writer, .author, td:nth-of-type(3)")
        if author_el:
            author = author_el.get_text(strip=True)

        return ScraperResult(
            external_id=content_id,
            title=title,
            category=category,
            author=author,
            published_date=date_text,
            url=url,
            file_url=None,
        )

    def _extract_content_id(self, href: str) -> str | None:
        """Extract contentId from href."""
        match = re.search(r"contentId[=,](\d+)", href)
        if match:
            return match.group(1)
        # Try numeric-only patterns
        match = re.search(r"(\d{4,})", href)
        return match.group(1) if match else None

    def _extract_board_id(self, href: str) -> str:
        match = re.search(r"boardId[=,](\d+)", href)
        return match.group(1) if match else "3"

    def _extract_date(self, row: BeautifulSoup) -> str | None:
        """Try to find a date in the row."""
        date_el = row.select_one(".date, .reg-date, td:nth-of-type(4)")
        if date_el:
            text = date_el.get_text(strip=True)
            # Try YYYY.MM.DD or YYYY-MM-DD
            match = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
            if match:
                y, m, d = match.group(1), match.group(2), match.group(3)
                return f"{y}-{int(m):02d}-{int(d):02d}"
        # Try anywhere in the row
        text = row.get_text()
        match = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
        if match:
            y, m, d = match.group(1), match.group(2), match.group(3)
            return f"{y}-{int(m):02d}-{int(d):02d}"
        return None

    def download_file(self, result: ScraperResult, dest_dir: Path) -> Path | None:
        """Download report PDF. Returns local path or None if restricted."""
        dest_dir.mkdir(parents=True, exist_ok=True)

        # First, visit the view page to find the actual download link
        file_url = result.file_url
        if not file_url:
            file_url = self._find_file_url(result.url)

        if not file_url:
            logger.info("No downloadable file found for: %s", result.title)
            return None

        # Ensure absolute URL
        if file_url.startswith("/"):
            file_url = f"{KCIF_BASE_URL}{file_url}"

        try:
            resp = self.client.get(file_url)

            if resp.status_code in (401, 403):
                logger.info("Restricted access for: %s", result.title)
                return None

            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                return None
            raise

        # Determine filename
        filename = self._get_filename(resp, result)
        filepath = dest_dir / filename

        filepath.write_bytes(resp.content)
        logger.info("Downloaded: %s (%d bytes)", filepath.name, len(resp.content))
        return filepath

    def _find_file_url(self, view_url: str) -> str | None:
        """Visit a report view page and find the PDF download link."""
        try:
            resp = self.client.get(view_url)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Failed to fetch view page: %s", view_url)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for download links (PDF, HWP, etc.)
        for link in soup.select("a[href]"):
            href = str(link.get("href", ""))
            text = link.get_text(strip=True).lower()

            # Check for file download patterns
            exts = [".pdf", ".hwp", "download", "fileDown"]
            if any(ext in href.lower() for ext in exts):
                return href
            if any(kw in text for kw in ["다운로드", "download", "pdf", "첨부"]):
                return href

        # Check for onclick handlers with file download
        for el in soup.select("[onclick]"):
            onclick = str(el.get("onclick", ""))
            match = re.search(r"((?:/[^'\"]+)?fileDown[^'\"]*)", onclick)
            if match:
                return match.group(1)

        return None

    def _get_filename(self, resp: httpx.Response, result: ScraperResult) -> str:
        """Extract filename from response headers or generate one."""
        cd = resp.headers.get("content-disposition", "")
        if cd:
            match = re.search(r'filename[*]?="?([^";\n]+)"?', cd)
            if match:
                return match.group(1).strip()

        # Generate a safe filename
        safe_title = re.sub(r"[^\w\s가-힣-]", "", result.title)[:60].strip()
        safe_title = re.sub(r"\s+", "_", safe_title)
        ext = ".pdf"
        content_type = resp.headers.get("content-type", "")
        if "hwp" in content_type:
            ext = ".hwp"
        return f"{result.external_id}_{safe_title}{ext}"


def file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
