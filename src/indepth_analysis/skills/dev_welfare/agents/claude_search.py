"""Shared Claude CLI web search utility for dev_welfare agents."""

import json
import logging
import subprocess

from indepth_analysis.models.euro_macro import ResearchFinding

logger = logging.getLogger(__name__)

_SEARCH_PROMPT_TEMPLATE = """\
당신은 리서치 어시스턴트입니다. 아래 주제에 대해 웹 검색을 수행하고 \
결과를 정리해주세요.

검색 주제: {topic}
검색 범위: {year}년 {month}월 전후
카테고리: {category}

반드시 웹 검색 도구를 사용하여 최신 정보를 수집하세요.

결과를 아래 JSON 배열 형식으로만 출력하세요. 다른 텍스트 없이 JSON만 출력하세요.
찾은 결과가 없으면 빈 배열 []을 출력하세요.

```json
[
  {{
    "title": "기사/보고서 제목",
    "summary": "핵심 내용 요약 (2~3문장)",
    "source_url": "https://...",
    "source_name": "출처 기관명",
    "published_date": "YYYY-MM-DD 또는 null"
  }}
]
```
"""

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT = 120


def claude_web_search(
    topic: str,
    year: int,
    month: int,
    category: str,
    model: str = _DEFAULT_MODEL,
) -> list[ResearchFinding]:
    """Run a Claude CLI web search and return structured findings."""
    prompt = _SEARCH_PROMPT_TEMPLATE.format(
        topic=topic,
        year=year,
        month=month,
        category=category,
    )

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--model",
                model,
                "--output-format",
                "text",
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI timed out for topic: %s", topic)
        return []

    if result.returncode != 0:
        logger.warning(
            "Claude CLI failed (exit %d) for topic: %s — %s",
            result.returncode,
            topic,
            result.stderr[:200],
        )
        return []

    return _parse_findings(result.stdout, category)


def _parse_findings(text: str, category: str) -> list[ResearchFinding]:
    """Extract JSON array from Claude CLI output."""
    # Try to find JSON array in the output
    text = text.strip()

    # Strip markdown code fences if present
    if "```" in text:
        lines = text.split("\n")
        json_lines: list[str] = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                json_lines.append(line)
        if json_lines:
            text = "\n".join(json_lines)

    # Find the JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("No JSON array found in Claude output")
        return []

    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON from Claude output")
        return []

    findings: list[ResearchFinding] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        findings.append(
            ResearchFinding(
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                source_url=item.get("source_url"),
                source_name=item.get("source_name", ""),
                published_date=item.get("published_date"),
                category=category,
            )
        )
    return findings
