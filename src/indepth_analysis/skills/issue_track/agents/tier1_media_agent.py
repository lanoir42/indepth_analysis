"""Tier 2 — Major financial/tech media agent."""

import logging
from datetime import UTC, datetime

from indepth_analysis.models.issue_track import Evidence
from indepth_analysis.skills.issue_track.agents.base import IssueAgent, IssueRunContext
from indepth_analysis.skills.issue_track.agents.claude_search import issue_web_search
from indepth_analysis.skills.issue_track.store import content_hash

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
당신은 투자 리서치 어시스턴트입니다. 반드시 웹 검색 도구를 사용하여 \
아래 이슈에 관한 **주요 언론 보도**를 수집하세요.

이슈 주제: {topic}
검색 기간: {since} 이후
키워드: {keywords}

우선 검색 매체 (이 매체들을 우선적으로 검색):
WSJ, Financial Times, Bloomberg, Reuters, NYT, The Information, \
TechCrunch, CNBC, Forbes, AP News, The Verge, Wired, MIT Technology Review

수집 기준:
- 이슈와 직접 관련된 사실 보도, 분석 기사
- 내부자 증언이나 익명 소스를 인용한 보도 포함
- 우려/반박/중립 시각 모두 포함

각 항목에 반드시 원본 URL을 포함하세요.
결과를 아래 JSON 배열 형식으로만 출력하세요:

```json
[
  {{
    "title": "기사 제목",
    "excerpt": "핵심 내용 요약 (3~5문장, 인용 포함)",
    "source_url": "https://...",
    "source_name": "매체명 (예: WSJ, Bloomberg)",
    "published_at": "YYYY-MM-DD 또는 null",
    "stance": "concern | dissent | rebuttal | neutral | factual"
  }}
]
```
결과가 없으면 [] 출력.
"""


class Tier1MediaAgent(IssueAgent):
    name = "tier1_media"
    tier = 2

    async def research(self, ctx: IssueRunContext) -> list[Evidence]:
        keywords = ", ".join(ctx.seed_keywords) if ctx.seed_keywords else ctx.topic
        prompt = _PROMPT_TEMPLATE.format(
            topic=ctx.topic,
            since=ctx.since,
            keywords=keywords,
        )
        items = issue_web_search(prompt, timeout=150)
        now = datetime.now(UTC).isoformat()
        results: list[Evidence] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("source_url", "")
            if not url:
                continue
            excerpt = item.get("excerpt", "")
            results.append(
                Evidence(
                    slug=ctx.slug,
                    tier=self.tier,
                    source_type="tier1_news",
                    source_name=item.get("source_name"),
                    canonical_url=url,
                    title=item.get("title"),
                    excerpt=excerpt,
                    full_text_hash=content_hash(excerpt) if excerpt else None,
                    published_at=item.get("published_at"),
                    fetched_at=now,
                    stance=item.get("stance", "neutral"),
                    credibility_score=4.5,
                )
            )
        logger.info("Tier1MediaAgent: %d items collected", len(results))
        return results
