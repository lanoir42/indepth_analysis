from indepth_analysis.data.kcif_client import KCIFScraper
from indepth_analysis.data.scraper_base import ScraperResult


class TestScraperResult:
    def test_basic_creation(self) -> None:
        r = ScraperResult(
            external_id="123",
            title="Test Report",
            url="https://example.com/123",
        )
        assert r.external_id == "123"
        assert r.title == "Test Report"
        assert r.category == ""
        assert r.file_url is None

    def test_full_creation(self) -> None:
        r = ScraperResult(
            external_id="456",
            title="Full Report",
            category="focus",
            author="Author",
            published_date="2026-01-15",
            url="https://example.com/456",
            file_url="https://example.com/456.pdf",
        )
        assert r.published_date == "2026-01-15"
        assert r.file_url == "https://example.com/456.pdf"


class TestKCIFScraper:
    def test_instance_creation(self) -> None:
        scraper = KCIFScraper()
        assert scraper.source_name == "KCIF"
        assert scraper.base_url == "https://www.kcif.or.kr"

    def test_custom_board_ids(self) -> None:
        scraper = KCIFScraper(board_ids=["3"])
        assert scraper._board_ids == ["3"]

    def test_extract_content_id(self) -> None:
        scraper = KCIFScraper()
        assert scraper._extract_content_id("contentId=12345") == "12345"
        assert scraper._extract_content_id("boardId=3,contentId=99999") == "99999"
        assert scraper._extract_content_id("javascript:void(0)") is None

    def test_extract_date(self) -> None:
        from bs4 import BeautifulSoup

        scraper = KCIFScraper()

        # With proper date element
        html = '<tr><td class="date">2026.02.15</td></tr>'
        row = BeautifulSoup(html, "html.parser").find("tr")
        assert scraper._extract_date(row) == "2026-02-15"

        # With date in text
        html = "<tr><td>Some text 2025-12-01 more text</td></tr>"
        row = BeautifulSoup(html, "html.parser").find("tr")
        assert scraper._extract_date(row) == "2025-12-01"

        # No date
        html = "<tr><td>No date here</td></tr>"
        row = BeautifulSoup(html, "html.parser").find("tr")
        assert scraper._extract_date(row) is None

    def test_get_filename(self) -> None:
        import httpx

        scraper = KCIFScraper()
        result = ScraperResult(
            external_id="123",
            title="테스트 보고서 제목",
            url="https://example.com/123",
        )

        # With content-disposition header
        resp = httpx.Response(
            200,
            headers={"content-disposition": 'attachment; filename="report.pdf"'},
        )
        assert scraper._get_filename(resp, result) == "report.pdf"

        # Without header, generate from title
        resp = httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
        )
        name = scraper._get_filename(resp, result)
        assert name.startswith("123_")
        assert name.endswith(".pdf")

    def test_protocol_conformance(self) -> None:
        """Verify KCIFScraper has the required BaseScraper attributes and methods."""
        scraper = KCIFScraper()
        assert hasattr(scraper, "source_name")
        assert hasattr(scraper, "base_url")
        assert hasattr(scraper, "scrape_listing")
        assert hasattr(scraper, "download_file")
        assert callable(scraper.scrape_listing)
        assert callable(scraper.download_file)
