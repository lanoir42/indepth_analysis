"""Tier 3 — Social media and blog agent (X, Substack, Reddit, blogs)."""

import logging
from datetime import UTC, datetime

from indepth_analysis.models.issue_track import Evidence
from indepth_analysis.skills.issue_track.agents.base import IssueAgent, IssueRunContext
from indepth_analysis.skills.issue_track.agents.claude_search import issue_web_search
from indepth_analysis.skills.issue_track.store import content_hash

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
당신은 투자 리서치 어시스턴트입니다. 반드시 웹 검색 도구를 사용하여 \
아래 이슈에 관한 **소셜미디어와 블로그 반응**을 수집하세요.

이슈 주제: {topic}
검색 기간: {since} 이후
키워드: {keywords}

검색 대상:
- X(Twitter): 업계 분석가, 전문가, 내부자의 반응
- Substack: 관련 뉴스레터 분석
- Reddit: r/MachineLearning, r/OpenAI, r/investing 등 관련 커뮤니티
- 개인 블로그, 독립 미디어

각 항목에 반드시:
1. 원본 URL
2. 작성자/계정 핸들 (X: @handle, Substack: substack명, Reddit: u/user)
3. 신뢰도 평가 (5개 축 각 0~5 점수)

결과를 아래 JSON 배열 형식으로만 출력하세요:

```json
[
  {{
    "title": "포스트/글 제목 또는 요약",
    "excerpt": "핵심 내용 (2~4문장, 인용 가능하면 인용)",
    "source_url": "https://...",
    "source_name": "작성자 이름 또는 블로그명",
    "source_handle": "x:@handle 또는 substack:도메인 또는 reddit:r/sub:u/user",
    "source_type": "x_post | substack | reddit | blog | other_social",
    "published_at": "YYYY-MM-DD 또는 null",
    "stance": "concern | dissent | rebuttal | neutral | factual",
    "credibility": {{
      "identity_verifiability": 0,
      "track_record": 0,
      "domain_expertise": 0,
      "sourcing_transparency": 0,
      "bias_disclosure": 0,
      "rationale": "평가 근거 1~2문장"
    }}
  }}
]
```
결과가 없으면 [] 출력.
"""


def _compute_score(cred: dict) -> float:
    weights = {
        "identity_verifiability": 0.15,
        "track_record": 0.25,
        "domain_expertise": 0.25,
        "sourcing_transparency": 0.20,
        "bias_disclosure": 0.15,
    }
    score = 0.0
    for key, weight in weights.items():
        val = cred.get(key, 0)
        try:
            score += float(val) * weight
        except (TypeError, ValueError):
            pass
    return round(score, 2)


class SocialBlogAgent(IssueAgent):
    name = "social_blog"
    tier = 3

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
            cred = item.get("credibility", {})
            score = _compute_score(cred) if cred else None
            results.append(
                Evidence(
                    slug=ctx.slug,
                    tier=self.tier,
                    source_type=item.get("source_type", "other_social"),
                    source_name=item.get("source_name"),
                    source_handle=item.get("source_handle"),
                    canonical_url=url,
                    title=item.get("title"),
                    excerpt=excerpt,
                    full_text_hash=content_hash(excerpt) if excerpt else None,
                    published_at=item.get("published_at"),
                    fetched_at=now,
                    stance=item.get("stance", "neutral"),
                    credibility_score=score,
                    credibility_basis=cred if cred else None,
                )
            )
        logger.info("SocialBlogAgent: %d items collected", len(results))
        return results
