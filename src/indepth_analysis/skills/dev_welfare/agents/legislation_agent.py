"""Legislation agent — searches Korean National Assembly and MOHW policy."""

import logging

from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.skills.base import BaseResearchAgent
from indepth_analysis.skills.dev_welfare.agents.claude_search import claude_web_search

logger = logging.getLogger(__name__)

_TOPICS = [
    "국회 보건복지위원회 법안 심의, 사회복지 관련 입법 동향",
    "보건복지부 정책 발표, 사회서비스 제도 변화, 복지 예산",
    "국제개발협력 기본법 개정, ODA 예산 국회 심의",
    "사회복지사 처우 개선, 복지 인력 정책",
]


class LegislationAgent(BaseResearchAgent):
    """Searches National Assembly and MOHW for welfare/ODA legislation."""

    name = "입법·정책"

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
                    category="입법·정책",
                )
                all_findings.extend(results)
            except Exception as e:
                logger.warning(
                    "Legislation search failed for topic: %s — %s", topic, e
                )

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
