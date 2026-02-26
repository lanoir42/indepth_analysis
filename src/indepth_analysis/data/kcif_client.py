import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup, Tag

from indepth_analysis.data.scraper_base import ScraperResult

logger = logging.getLogger(__name__)

KCIF_BASE_URL = "https://www.kcif.or.kr"
KCIF_LIST_URL = f"{KCIF_BASE_URL}/report/reportList"
KCIF_DOWNLOAD_URL = f"{KCIF_BASE_URL}/common/file/reportFileDownload"
KCIF_AUTH_URL = f"{KCIF_BASE_URL}/comm/AuthCheck"

# Report link URL patterns (section → view path)
VIEW_PATTERNS = ("reportView", "financeView", "economyView")

DEFAULT_TIMEOUT = 30.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

ITEMS_PER_PAGE = 100  # max pp the site honors


class KCIFScraper:
    """Scraper for KCIF (Korea Center for International Finance) reports."""

    source_name: str = "KCIF"
    base_url: str = KCIF_BASE_URL

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
            )
            # Establish session cookies
            self._client.get(KCIF_LIST_URL)
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
        """Scrape report metadata from the KCIF listing page."""
        all_results: list[ScraperResult] = []
        page = 1
        max_pages = 50  # safety cap

        while page <= max_pages:
            params: dict[str, str | int] = {
                "pg": page,
                "pp": ITEMS_PER_PAGE,
            }
            if year:
                params["year"] = year
            if month:
                params["month"] = f"{month:02d}"

            try:
                resp = self.client.get(KCIF_LIST_URL, params=params)
                resp.raise_for_status()
            except httpx.HTTPError:
                logger.warning("HTTP error fetching page %d", page, exc_info=True)
                break

            page_results = self._parse_listing_page(resp.text)
            if not page_results:
                break

            all_results.extend(page_results)
            logger.info(
                "Page %d: scraped %d reports (total: %d)",
                page,
                len(page_results),
                len(all_results),
            )

            if limit and len(all_results) >= limit:
                all_results = all_results[:limit]
                break

            # If we got fewer than a full page, we're done
            if len(page_results) < ITEMS_PER_PAGE:
                break

            page += 1

        return all_results

    def _parse_listing_page(self, html: str) -> list[ScraperResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[ScraperResult] = []
        seen_ids: set[str] = set()

        for li in soup.select("li"):
            # Must have a report view link
            link = li.select_one("a[href]")
            if not link:
                continue
            href = str(link.get("href", ""))
            if not any(vp in href for vp in VIEW_PATTERNS):
                continue

            # Must have author/date info (filters out sidebar duplicates)
            txt_wrap = li.select_one("div.txt_wrap")
            if not txt_wrap:
                continue

            result = self._parse_item(li, link, href, txt_wrap)
            if result and result.external_id not in seen_ids:
                seen_ids.add(result.external_id)
                results.append(result)

        return results

    def _parse_item(
        self,
        li: Tag,
        link: Tag,
        href: str,
        txt_wrap: Tag,
    ) -> ScraperResult | None:
        title = link.get_text(strip=True)
        if not title:
            return None

        # Extract rpt_no as external ID
        rpt_match = re.search(r"rpt_no=(\d+)", href)
        if not rpt_match:
            return None
        rpt_no = rpt_match.group(1)

        # Build full view URL
        url = f"{KCIF_BASE_URL}{href}" if href.startswith("/") else href

        # Category from h5.tit_bar
        category = ""
        h5 = li.select_one("h5.tit_bar")
        if h5:
            raw = h5.get_text(strip=True)
            # Clean "정기보고서 > 국제금융속보" → "국제금융속보"
            parts = raw.split(">")
            category = parts[-1].strip() if parts else raw

        # Author and date from div.txt_wrap spans
        spans = txt_wrap.select("span")
        author = spans[0].get_text(strip=True) if spans else ""
        date_text = spans[1].get_text(strip=True) if len(spans) > 1 else ""
        published_date = self._parse_date(date_text)

        # Download file number (fno) from reportdownload onclick
        file_url = None
        dl_btn = li.select_one("[onclick*='reportdownload']")
        if dl_btn:
            onclick = str(dl_btn.get("onclick", ""))
            fno_match = re.search(r"reportdownload\('([^']+)'\)", onclick)
            if fno_match:
                fno = fno_match.group(1)
                file_url = f"{KCIF_DOWNLOAD_URL}?atch_no={fno}&lang=KR"

        return ScraperResult(
            external_id=rpt_no,
            title=title,
            category=category,
            author=author,
            published_date=published_date,
            url=url,
            file_url=file_url,
        )

    def _parse_date(self, text: str) -> str | None:
        """Parse date from '2026.02.26' format to '2026-02-26'."""
        match = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
        if match:
            y, m, d = match.group(1), match.group(2), match.group(3)
            return f"{y}-{int(m):02d}-{int(d):02d}"
        return None

    def download_file(self, result: ScraperResult, dest_dir: Path) -> Path | None:
        """Download report PDF. Returns local path or None if restricted."""
        dest_dir.mkdir(parents=True, exist_ok=True)

        file_url = result.file_url
        if not file_url:
            # Try to find download link on the view page
            file_url = self._find_file_url(result.url)

        if not file_url:
            logger.info("No downloadable file for: %s", result.title)
            return None

        # Ensure absolute URL
        if file_url.startswith("/"):
            file_url = f"{KCIF_BASE_URL}{file_url}"

        try:
            resp = self.client.get(file_url)

            if resp.status_code in (401, 403):
                logger.info("Restricted: %s", result.title)
                return None

            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                return None
            raise

        # Verify we got actual file content
        if len(resp.content) < 100:
            logger.warning(
                "Tiny response for %s (%d bytes), skipping",
                result.title,
                len(resp.content),
            )
            return None

        filename = self._get_filename(resp, result)
        filepath = dest_dir / filename

        filepath.write_bytes(resp.content)
        logger.info("Downloaded: %s (%d bytes)", filepath.name, len(resp.content))
        return filepath

    def _find_file_url(self, view_url: str) -> str | None:
        """Visit a report view page and find the download link."""
        try:
            resp = self.client.get(view_url)
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Failed to fetch: %s", view_url)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for reportdownload onclick
        dl_btn = soup.select_one("[onclick*='reportdownload']")
        if dl_btn:
            onclick = str(dl_btn.get("onclick", ""))
            match = re.search(r"reportdownload\('([^']+)'\)", onclick)
            if match:
                fno = match.group(1)
                return f"{KCIF_DOWNLOAD_URL}?atch_no={fno}&lang=KR"

        return None

    def _get_filename(self, resp: httpx.Response, result: ScraperResult) -> str:
        """Extract filename from response headers or generate one."""
        cd = resp.headers.get("content-disposition", "")
        if cd:
            match = re.search(r'filename[*]?="?([^";\n]+)"?', cd)
            if match:
                name = match.group(1).strip()
                # Decode URL-encoded filenames
                if "%" in name:
                    name = unquote(name)
                return name

        # Generate a safe filename
        safe_title = re.sub(r"[^\w\s가-힣-]", "", result.title)
        safe_title = safe_title[:60].strip()
        safe_title = re.sub(r"\s+", "_", safe_title)
        return f"{result.external_id}_{safe_title}.pdf"


def file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
