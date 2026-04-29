"""Tier 1 — Primary source agent: official documents, IR, SEC filings."""

import logging
from datetime import UTC, datetime

from indepth_analysis.models.issue_track import Evidence
from indepth_analysis.skills.issue_track.agents.base import IssueAgent, IssueRunContext
from indepth_analysis.skills.issue_track.agents.claude_search import issue_web_search
from indepth_analysis.skills.issue_track.store import content_hash

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
당신은 투자 리서치 어시스턴트입니다. 반드시 웹 검색 도구를 사용하여 \
아래 이슈에 관한 **1차 원본 자료**를 수집하세요.

이슈 주제: {topic}
검색 기간: {since} 이후
키워드: {keywords}

수집 대상:
- 회사 공식 블로그 / IR(Investor Relations) 발표
- SEC EDGAR 공시 (8-K, 10-K, Form 990 등)
- 회사 X(Twitter) 공식 계정 발표
- 공식 보도자료 (PR Newswire, BusinessWire 등)
- 이슈와 직접 관련된 원본 데이터 발표

각 항목에 반드시 원본 URL을 포함하세요.
결과를 아래 JSON 배열 형식으로만 출력하세요:

```json
[
  {{
    "title": "문서/발표 제목",
    "excerpt": "핵심 내용 요약 (3~5문장, 수치 포함)",
    "source_url": "https://...",
    "source_name": "출처 기관명 (예: OpenAI Blog, SEC EDGAR)",
    "source_type": "ir_blog | sec_filing | press_release | official_x | other_primary",
    "published_at": "YYYY-MM-DD 또는 null",
    "stance": "factual | concern | rebuttal | neutral"
  }}
]
```
결과가 없으면 [] 출력.
"""


class PrimarySourceAgent(IssueAgent):
    name = "primary_source"
    tier = 1

    async def research(self, ctx: IssueRunContext) -> list[Evidence]:
        keywords = ", ".join(ctx.seed_keywords) if ctx.seed_keywords else ctx.topic
        prompt = _PROMPT_TEMPLATE.format(
            topic=ctx.topic,
            since=ctx.since,
            keywords=keywords,
        )
        items = issue_web_search(prompt, timeout=120)
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
                    source_type=item.get("source_type", "other_primary"),
                    source_name=item.get("source_name"),
                    canonical_url=url,
                    title=item.get("title"),
                    excerpt=excerpt,
                    full_text_hash=content_hash(excerpt) if excerpt else None,
                    published_at=item.get("published_at"),
                    fetched_at=now,
                    stance=item.get("stance", "factual"),
                    credibility_score=5.0,
                )
            )
        logger.info("PrimarySourceAgent: %d items collected", len(results))
        return results
