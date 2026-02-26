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

    def test_parse_date(self) -> None:
        scraper = KCIFScraper()
        assert scraper._parse_date("2026.02.15") == "2026-02-15"
        assert scraper._parse_date("2025-12-01") == "2025-12-01"
        assert scraper._parse_date("2026/1/5") == "2026-01-05"
        assert scraper._parse_date("no date") is None

    def test_get_filename_from_header(self) -> None:
        import httpx

        scraper = KCIFScraper()
        result = ScraperResult(
            external_id="123",
            title="테스트 보고서 제목",
            url="https://example.com/123",
        )

        resp = httpx.Response(
            200,
            headers={"content-disposition": "attachment;filename=BR260226.pdf"},
        )
        assert scraper._get_filename(resp, result) == "BR260226.pdf"

    def test_get_filename_generated(self) -> None:
        import httpx

        scraper = KCIFScraper()
        result = ScraperResult(
            external_id="123",
            title="테스트 보고서 제목",
            url="https://example.com/123",
        )

        resp = httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
        )
        name = scraper._get_filename(resp, result)
        assert name.startswith("123_")
        assert name.endswith(".pdf")

    def test_parse_listing_page(self) -> None:
        """Test parsing a realistic KCIF listing HTML fragment."""
        scraper = KCIFScraper()
        html = """
        <html><body>
        <li>
            <h5 class="tit_bar">정기보고서 &gt; 국제금융속보</h5>
            <div class="tit_box">
                <a href="/annual/reportView?rpt_no=36726&mn=001002">
                    <p>[2.26] 미국 트럼프, 고관세 정책</p>
                </a>
            </div>
            <div class="txt_bot">
                <div class="txt_wrap">
                    <span>해외동향부</span>
                    <span>2026.02.26</span>
                </div>
                <div class="btn_wrap">
                    <button class="btn down"
                     onclick="reportdownload('abc123');">
                     다운로드</button>
                </div>
            </div>
        </li>
        </body></html>
        """
        results = scraper._parse_listing_page(html)
        assert len(results) == 1
        r = results[0]
        assert r.external_id == "36726"
        assert r.title == "[2.26] 미국 트럼프, 고관세 정책"
        assert r.category == "국제금융속보"
        assert r.author == "해외동향부"
        assert r.published_date == "2026-02-26"
        assert "atch_no=abc123" in r.file_url

    def test_parse_listing_page_skips_sidebar(self) -> None:
        """Items without txt_wrap (sidebar duplicates) are skipped."""
        scraper = KCIFScraper()
        html = """
        <html><body>
        <li>
            <h5 class="tit_bar">국제금융속보</h5>
            <div class="tit_box">
                <a href="/annual/reportView?rpt_no=36726&mn=001002">
                    <p>Title</p>
                </a>
            </div>
        </li>
        </body></html>
        """
        results = scraper._parse_listing_page(html)
        assert len(results) == 0

    def test_protocol_conformance(self) -> None:
        """Verify KCIFScraper has the required BaseScraper attributes."""
        scraper = KCIFScraper()
        assert hasattr(scraper, "source_name")
        assert hasattr(scraper, "base_url")
        assert hasattr(scraper, "scrape_listing")
        assert hasattr(scraper, "download_file")
        assert callable(scraper.scrape_listing)
        assert callable(scraper.download_file)
