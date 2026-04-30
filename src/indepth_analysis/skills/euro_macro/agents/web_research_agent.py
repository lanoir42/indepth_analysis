"""Web research agent — uses Claude CLI subprocesses with WebSearch/WebFetch tools."""

import asyncio
import json
import logging
import re
from collections import namedtuple

from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
from indepth_analysis.skills.base import BaseResearchAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Topic definitions
# ---------------------------------------------------------------------------

WebTopic = namedtuple("WebTopic", ["key", "category", "query_ko", "target_domains"])

WEB_TOPICS: tuple[WebTopic, ...] = (
    WebTopic(
        key="ecb_monetary",
        category="ECB 통화정책",
        query_ko="ECB 통화정책 금리 결정 최신 동향 {year}년 {month}월",
        target_domains=("ecb.europa.eu", "reuters.com", "ft.com"),
    ),
    WebTopic(
        key="eurostat_data",
        category="유로존 통계",
        query_ko="유로존 GDP 인플레이션 실업률 최신 통계 {year}년 {month}월",
        target_domains=("ec.europa.eu", "eurostat.ec.europa.eu"),
    ),
    WebTopic(
        key="financial_market",
        category="유럽 금융시장",
        query_ko="유럽 금융시장 EUR USD 환율 국채 주식시장 동향 {year}년 {month}월",
        target_domains=("bloomberg.com", "reuters.com", "ft.com"),
    ),
    WebTopic(
        key="eu_politics",
        category="EU 정치",
        query_ko="EU 유럽 정치 독일 프랑스 정부 최신 동향 {year}년 {month}월",
        target_domains=("reuters.com", "politico.eu", "ft.com"),
    ),
    WebTopic(
        key="trade_tariff",
        category="무역·관세",
        query_ko="미국 관세 EU 무역 분쟁 대응 최신 동향 {year}년 {month}월",
        target_domains=("reuters.com", "ft.com", "trade.ec.europa.eu"),
    ),
    WebTopic(
        key="energy_commodity",
        category="에너지·원자재",
        query_ko="유럽 에너지 가격 천연가스 원유 공급 동향 {year}년 {month}월",
        target_domains=("reuters.com", "iea.org", "ft.com"),
    ),
    WebTopic(
        key="fiscal_sovereign",
        category="재정·국채",
        query_ko="유럽 재정정책 부채 국채 스프레드 독일 이탈리아 {year}년 {month}월",
        target_domains=("reuters.com", "ft.com", "imf.org"),
    ),
    WebTopic(
        key="bank_credit",
        category="은행·신용",
        query_ko="유럽 은행 신용 금융안정 스트레스 {year}년 {month}월",
        target_domains=("ecb.europa.eu", "reuters.com", "ft.com"),
    ),
    WebTopic(
        key="eu_politics_media",
        category="유럽 정치지형 (언론)",
        query_ko=(
            "유럽 정치지형 극우 포퓰리즘 연립정부 선거 {year}년 {month}월 "
            "Politico Foreign Affairs Economist 분석"
        ),
        target_domains=("politico.eu", "foreignaffairs.com", "economist.com", "ft.com"),
    ),
    WebTopic(
        key="eu_politics_research",
        category="유럽 정치지형 (연구기관)",
        query_ko=(
            "유럽 정치 리스크 지정학 민주주의 포퓰리즘 {year}년 {month}월 "
            "ECFR Bruegel Chatham House 싱크탱크 보고서"
        ),
        target_domains=("ecfr.eu", "bruegel.org", "chathamhouse.org", "bertelsmann-stiftung.de"),
    ),
)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_TOPIC_PROMPT = """\
당신은 유럽 거시경제 리서치 전문가입니다. WebSearch와 WebFetch 도구만을 사용하여 \
아래 주제에 대한 최신 정보를 조사하고 결과를 한국어로 정리해 주세요.

## 조사 주제
{query}

## 우선 참고 도메인
{domains}

## 출력 형식
번호가 붙은 항목으로 핵심 발견 사항을 3~5개 작성하세요. 각 항목은 다음 구조를 따릅니다:

1. [제목: 핵심 내용을 요약한 한 문장]
   [요약: 구체적인 수치와 사실을 포함한 2~3문장 설명]
   URL: [출처 URL]
   날짜: [YYYY-MM-DD 형식, 확인 불가 시 생략]

## 주의사항
- WebSearch와 WebFetch 이외의 도구는 사용하지 마세요.
- 각 항목은 반드시 고유한 출처를 기반으로 하세요.
- 수치(금리, 물가상승률, 성장률 등)를 최대한 포함하세요.
- 날짜는 가능한 경우 YYYY-MM-DD 형식으로 기재하세요.
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_URL_RE = re.compile(r"URL:\s*(https?://\S+)", re.IGNORECASE)
_DATE_LINE_RE = re.compile(r"날짜:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def _parse_findings(text: str, category: str) -> list[ResearchFinding]:
    """Parse numbered findings from agent output text.

    Expected loose format per item::

        1. [제목]
           [요약 줄들]
           URL: https://...
           날짜: YYYY-MM-DD
    """
    findings: list[ResearchFinding] = []

    # Split on numbered list markers (1. / 2. etc.) at start of line
    # Keep the delimiter so we can use it.
    parts = re.split(r"(?m)^(\d+)\.\s+", text)
    # parts[0] is preamble (discard); then alternating [number, content] pairs
    items: list[str] = []
    i = 1
    while i < len(parts):
        # parts[i] is the number, parts[i+1] is the content block
        if i + 1 < len(parts):
            items.append(parts[i + 1])
        i += 2

    for block in items:
        lines = [ln.rstrip() for ln in block.splitlines()]
        if not lines:
            continue

        # First non-empty line is the title (strip leading [제목:] markers if any)
        title_line = ""
        body_lines: list[str] = []
        source_url: str | None = None
        published_date: str | None = None

        found_title = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if found_title:
                    body_lines.append("")
                continue

            url_match = _URL_RE.match(stripped)
            date_match = _DATE_LINE_RE.match(stripped)

            if url_match:
                source_url = url_match.group(1).rstrip(".")
                continue
            if date_match:
                published_date = date_match.group(1)
                continue

            if not found_title:
                # Strip surrounding brackets like [제목: ...]
                title_line = re.sub(r"^\[제목:\s*", "", stripped).rstrip("]")
                found_title = True
            else:
                # Strip leading bracket content like [요약: ...]
                cleaned = re.sub(r"^\[요약:\s*", "", stripped).rstrip("]")
                body_lines.append(cleaned)

        if not title_line:
            continue

        summary = " ".join(ln for ln in body_lines if ln).strip()
        if not summary:
            summary = title_line

        # Fall back: extract date from anywhere in block if not found on dedicated line
        if published_date is None:
            m = _DATE_RE.search(block)
            if m:
                published_date = m.group(1)

        findings.append(
            ResearchFinding(
                title=title_line,
                summary=summary,
                source_url=source_url or None,
                source_name=category,
                published_date=published_date,
                category=category,
            )
        )

    return findings


def _collect_text_from_stream(stdout: str) -> str:
    """Extract assistant text from stream-json output lines."""
    text_parts: list[str] = []
    result_text = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type", "")
        if t == "assistant":
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block["text"])
        elif t == "result" and obj.get("subtype") == "success":
            r = (obj.get("result") or "").strip()
            if r:
                result_text = r

    return result_text or "".join(text_parts)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class WebResearchAgent(BaseResearchAgent):
    """Researches European macro topics via Claude CLI subprocesses with web tools."""

    name = "WebResearch"

    def __init__(
        self,
        *,
        model: str = "claude-opus-4-20250514",
        max_concurrency: int = 4,
        timeout_per_topic: float = 120.0,
    ) -> None:
        self.model = model
        self.max_concurrency = max_concurrency
        self.timeout_per_topic = timeout_per_topic

    async def research(self, year: int, month: int) -> AgentResult:
        """Run all web research topics concurrently and return aggregated findings."""
        semaphore = asyncio.Semaphore(self.max_concurrency)
        queries = [
            topic.query_ko.format(year=year, month=month) for topic in WEB_TOPICS
        ]

        tasks = [
            self._research_topic(topic, year, month, semaphore)
            for topic in WEB_TOPICS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_findings: list[ResearchFinding] = []
        seen: set[tuple[str, str | None]] = set()  # (title, url) dedup keys

        for topic, result in zip(WEB_TOPICS, results):
            if isinstance(result, BaseException):
                logger.error("WebResearch topic %s raised: %s", topic.key, result)
                # Include an error placeholder finding so callers know what failed
                all_findings.append(
                    ResearchFinding(
                        title=f"[오류] {topic.category} 조사 실패",
                        summary=str(result),
                        source_name=topic.category,
                        category=topic.category,
                    )
                )
                continue

            for finding in result:
                dedup_key = (finding.title, finding.source_url)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                all_findings.append(finding)

        return AgentResult(
            agent_name=self.name,
            findings=all_findings,
            search_queries=queries,
        )

    async def _research_topic(
        self,
        topic: WebTopic,
        year: int,
        month: int,
        semaphore: asyncio.Semaphore,
    ) -> list[ResearchFinding]:
        """Run a single topic subprocess and parse results."""
        async with semaphore:
            query = topic.query_ko.format(year=year, month=month)
            domains_str = ", ".join(topic.target_domains)
            prompt = _TOPIC_PROMPT.format(query=query, domains=domains_str)

            cmd = [
                "claude",
                "-p", prompt,
                "--allowedTools", "WebSearch WebFetch",
                "--output-format", "stream-json",
                "--verbose",
                "--model", self.model,
            ]

            logger.info("WebResearch: starting topic %s", topic.key)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=self.timeout_per_topic,
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()  # drain
                    raise RuntimeError(
                        f"Topic {topic.key!r} timed out after {self.timeout_per_topic}s"
                    )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "claude CLI not found in PATH — is it installed?"
                ) from exc

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                logger.warning(
                    "WebResearch topic %s exited %d: %s",
                    topic.key,
                    proc.returncode,
                    stderr[:300],
                )
                raise RuntimeError(
                    f"Claude CLI exited {proc.returncode} for topic {topic.key!r}: "
                    f"{stderr[:200]}"
                )

            text = _collect_text_from_stream(stdout)
            if not text:
                logger.warning("WebResearch topic %s: no text in output", topic.key)
                return []

            findings = _parse_findings(text, topic.category)
            logger.info(
                "WebResearch: topic %s → %d findings", topic.key, len(findings)
            )
            return findings
