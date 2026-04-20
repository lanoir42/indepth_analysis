"""Journal agent — searches academic journals via Claude CLI."""

import logging

from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.skills.base import BaseResearchAgent
from indepth_analysis.skills.dev_welfare.agents.claude_search import claude_web_search

logger = logging.getLogger(__name__)

_TOPICS = [
    "국제개발협력 최신 학술 논문 (World Development, JIDS, Development Policy Review)",
    "사회복지행정 최신 학술 논문 (Social Work, BJSW, 한국사회복지학)",
    "한국 ODA 효과성 평가, 개발협력 임팩트 연구",
    "SDGs 이행 현황, 지속가능개발 학술 연구 동향",
]


class JournalAgent(BaseResearchAgent):
    """Searches academic journals for development and welfare research."""

    name = "학술저널"

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
                    category="학술",
                )
                all_findings.extend(results)
            except Exception as e:
                logger.warning("Journal search failed for topic: %s — %s", topic, e)

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
