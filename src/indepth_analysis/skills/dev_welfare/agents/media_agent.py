"""Media agent — searches development/welfare media via Claude CLI."""

import logging

from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.skills.base import BaseResearchAgent
from indepth_analysis.skills.dev_welfare.agents.claude_search import claude_web_search

logger = logging.getLogger(__name__)

_TOPICS = [
    "한국 국제개발협력 뉴스, ODA 관련 언론 보도",
    "사회복지 정책 뉴스, 복지 제도 변화 언론 보도 (한국)",
    "Devex, Guardian Global Development 등 국제개발 영문 미디어 최신 뉴스",
    "임팩트 투자, 사회적기업, 소셜 이노베이션 동향",
]


class DevWelfareMediaAgent(BaseResearchAgent):
    """Searches development/welfare media — Devex, Guardian, Korean news."""

    name = "미디어"

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
                    category="미디어",
                )
                all_findings.extend(results)
            except Exception as e:
                logger.warning("Media search failed for topic: %s — %s", topic, e)

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
