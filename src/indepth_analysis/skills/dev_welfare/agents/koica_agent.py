"""KOICA agent — searches KOICA news and ODA projects via Claude CLI."""

import logging

from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.skills.base import BaseResearchAgent
from indepth_analysis.skills.dev_welfare.agents.claude_search import claude_web_search

logger = logging.getLogger(__name__)

_TOPICS = [
    "KOICA(한국국제협력단) 신규 사업 공고 및 ODA 프로젝트 동향",
    "한국 ODA 정책 변화, 예산, 신규 협력국 확대",
    "KOICA 개발협력 성과평가 및 사업 결과 보고",
]


class KOICAAgent(BaseResearchAgent):
    """Searches KOICA news, project announcements, and ODA policy."""

    name = "KOICA"

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
                    category="KOICA",
                )
                all_findings.extend(results)
            except Exception as e:
                logger.warning("KOICA search failed for topic: %s — %s", topic, e)

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
