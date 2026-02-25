from datetime import datetime

from indepth_analysis.analysis.news_calendar import parse_calendar, parse_news


class TestParseNews:
    def test_basic_parsing(self):
        raw = [
            {
                "title": "Test Article",
                "publisher": "TestPub",
                "link": "https://example.com",
                "providerPublishTime": 1700000000,
                "thumbnail": {
                    "resolutions": [
                        {
                            "url": "https://img.com/small.jpg",
                            "width": 100,
                            "height": 50,
                        },
                        {
                            "url": "https://img.com/large.jpg",
                            "width": 800,
                            "height": 400,
                        },
                    ]
                },
            }
        ]
        articles = parse_news(raw)
        assert len(articles) == 1
        assert articles[0].title == "Test Article"
        assert articles[0].publisher == "TestPub"
        assert articles[0].link == "https://example.com"

    def test_picks_largest_thumbnail(self):
        raw = [
            {
                "title": "Test",
                "publisher": "Pub",
                "link": "https://example.com",
                "thumbnail": {
                    "resolutions": [
                        {
                            "url": "https://img.com/small.jpg",
                            "width": 100,
                            "height": 50,
                        },
                        {
                            "url": "https://img.com/large.jpg",
                            "width": 800,
                            "height": 400,
                        },
                        {
                            "url": "https://img.com/med.jpg",
                            "width": 400,
                            "height": 200,
                        },
                    ]
                },
            }
        ]
        articles = parse_news(raw)
        assert articles[0].thumbnail is not None
        assert articles[0].thumbnail.url == "https://img.com/large.jpg"
        assert articles[0].thumbnail.width == 800

    def test_max_articles_limit(self):
        raw = [
            {
                "title": f"Article {i}",
                "publisher": "Pub",
                "link": f"https://example.com/{i}",
            }
            for i in range(20)
        ]
        articles = parse_news(raw, max_articles=5)
        assert len(articles) == 5

    def test_no_thumbnail(self):
        raw = [
            {
                "title": "No Thumb",
                "publisher": "Pub",
                "link": "https://example.com",
            }
        ]
        articles = parse_news(raw)
        assert len(articles) == 1
        assert articles[0].thumbnail is None

    def test_empty_input(self):
        assert parse_news([]) == []

    def test_published_timestamp(self):
        raw = [
            {
                "title": "Test",
                "publisher": "Pub",
                "link": "https://example.com",
                "providerPublishTime": 1700000000,
            }
        ]
        articles = parse_news(raw)
        assert "2023" in articles[0].published
        assert "UTC" in articles[0].published


class TestParseCalendar:
    def test_earnings_date(self):
        raw = {
            "Earnings Date": [datetime(2025, 1, 28)],
            "Earnings Average": 2.95,
            "Earnings Low": 2.80,
            "Earnings High": 3.10,
        }
        events = parse_calendar(raw)
        assert len(events) >= 1
        earnings = [e for e in events if e.event == "Earnings"]
        assert len(earnings) == 1
        assert "2025-01-28" in earnings[0].date
        assert "2.95" in earnings[0].details

    def test_dividend_date(self):
        raw = {
            "Dividend Date": datetime(2025, 3, 15),
        }
        events = parse_calendar(raw)
        dividend = [e for e in events if e.event == "Dividend"]
        assert len(dividend) == 1
        assert "2025-03-15" in dividend[0].date

    def test_ex_dividend_date(self):
        raw = {
            "Ex-Dividend Date": datetime(2025, 2, 20),
        }
        events = parse_calendar(raw)
        ex_div = [e for e in events if e.event == "Ex-Dividend"]
        assert len(ex_div) == 1

    def test_empty_calendar(self):
        assert parse_calendar({}) == []

    def test_none_calendar(self):
        assert parse_calendar(None) == []
