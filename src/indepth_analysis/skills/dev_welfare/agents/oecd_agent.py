"""OECD agent — searches OECD DAC, World Bank, UN agencies via Claude CLI."""

import logging

from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.skills.base import BaseResearchAgent
from indepth_analysis.skills.dev_welfare.agents.claude_search import claude_web_search

logger = logging.getLogger(__name__)

_TOPICS = [
    "OECD DAC 한국 ODA 동료평가, GNI 대비 ODA 비율, 다자 ODA 동향",
    "World Bank 한국 관련 개발협력 보고서, 글로벌 빈곤 데이터",
    "UNDP, UNICEF, WHO 한국 관련 프로그램, SDGs 이행 평가",
    "CGD(Center for Global Development) 정책 분석, 원조 효과성 연구",
]


class OECDAgent(BaseResearchAgent):
    """Searches OECD DAC, World Bank, and UN agencies for Korea ODA data."""

    name = "국제기구"

    async def research(self, year: int, month: int) -> AgentResult:
        all_findings: list[ResearchFinding] = []
        queries: list[str] = []

        for topic in _TOPICS:
            queries.append(topic)
            try:
                results = claude_web_search(
                    topic=topic,
                    year=year,
                    month=month,
                    category="국제기구",
                )
                all_findings.extend(results)
            except Exception as e:
                logger.warning("OECD search failed for topic: %s — %s", topic, e)

        seen_urls: set[str] = set()
        unique: list[ResearchFinding] = []
        for f in all_findings:
            key = f.source_url or f.title
            if key not in seen_urls:
                seen_urls.add(key)
                unique.append(f)

        return AgentResult(
            agent_name=self.name, findings=unique, search_queries=queries
        )
