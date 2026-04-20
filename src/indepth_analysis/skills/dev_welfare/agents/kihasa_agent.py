"""KIHASA agent — searches Korea Institute for Health and Social Affairs."""

import logging

from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.skills.base import BaseResearchAgent
from indepth_analysis.skills.dev_welfare.agents.claude_search import claude_web_search

logger = logging.getLogger(__name__)

_TOPICS = [
    "한국보건사회연구원(KIHASA) 최신 연구보고서 및 정책브리프",
    "한국보건사회연구원 사회복지 정책 제안 및 복지 동향 분석",
    "KIHASA 보건·복지 이슈앤포커스, 연구 세미나",
]


class KIHASAAgent(BaseResearchAgent):
    """Searches KIHASA research reports and policy briefs."""

    name = "KIHASA"

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
                    category="KIHASA",
                )
                all_findings.extend(results)
            except Exception as e:
                logger.warning("KIHASA search failed for topic: %s — %s", topic, e)

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
