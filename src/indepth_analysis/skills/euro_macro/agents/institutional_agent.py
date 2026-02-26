"""Institutional agent — searches ECB, IMF, BIS, OECD official sources."""

import logging

import httpx
from bs4 import BeautifulSoup

from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.skills.base import BaseResearchAgent

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.google.com/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 15.0

# Target institutional domains
INSTITUTIONAL_DOMAINS = [
    "ecb.europa.eu",
    "imf.org",
    "bis.org",
    "oecd.org",
    "ec.europa.eu",
    "eurostat.ec.europa.eu",
]


def _build_queries(year: int, month: int) -> list[str]:
    return [
        f"site:ecb.europa.eu monetary policy decision {year}",
        f"site:imf.org euro area outlook {year}",
        f"site:bis.org european financial stability {year}",
        f"site:oecd.org euro area economic survey {year}",
        f"ECB press conference {year} {month:02d}",
        f"Eurostat GDP inflation {year}",
    ]


async def _search_google(
    client: httpx.AsyncClient, query: str
) -> list[ResearchFinding]:
    """Execute a single Google search and parse results."""
    findings: list[ResearchFinding] = []
    try:
        resp = await client.get(
            SEARCH_URL,
            params={"q": query, "num": 5, "hl": "en"},
            headers=HEADERS,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        logger.warning("Search failed for query: %s", query)
        return findings

    soup = BeautifulSoup(resp.text, "html.parser")
    for g in soup.select("div.g"):
        link = g.select_one("a[href]")
        title_el = g.select_one("h3")
        snippet_el = g.select_one("div.VwiC3b, span.aCOpRe, div[data-sncf]")

        if not link or not title_el:
            continue

        href = link.get("href", "")
        if not isinstance(href, str) or not href.startswith("http"):
            continue

        title = title_el.get_text(strip=True)
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        source = _match_institution(href)
        findings.append(
            ResearchFinding(
                title=title,
                summary=snippet or title,
                source_url=href,
                source_name=source,
                category="기관보고서",
            )
        )
    return findings


def _match_institution(url: str) -> str:
    """Identify the institutional source from a URL."""
    url_lower = url.lower()
    mapping = {
        "ecb.europa.eu": "ECB",
        "imf.org": "IMF",
        "bis.org": "BIS",
        "oecd.org": "OECD",
        "ec.europa.eu": "European Commission",
        "eurostat": "Eurostat",
    }
    for domain, name in mapping.items():
        if domain in url_lower:
            return name
    try:
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


class InstitutionalAgent(BaseResearchAgent):
    """Searches official institutional sources (ECB, IMF, BIS, OECD)."""

    name = "Institutional"

    async def research(self, year: int, month: int) -> AgentResult:
        queries = _build_queries(year, month)
        all_findings: list[ResearchFinding] = []

        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT, follow_redirects=True
            ) as client:
                for q in queries:
                    results = await _search_google(client, q)
                    all_findings.extend(results)
        except Exception as e:
            logger.exception("Institutional agent error")
            return AgentResult(
                agent_name=self.name, search_queries=queries, error=str(e)
            )

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique: list[ResearchFinding] = []
        for f in all_findings:
            if f.source_url and f.source_url not in seen_urls:
                seen_urls.add(f.source_url)
                unique.append(f)

        return AgentResult(
            agent_name=self.name, findings=unique, search_queries=queries
        )
