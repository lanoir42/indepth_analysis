"""Orchestrator — dispatches agents in parallel and synthesizes via Claude API."""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import anthropic

from indepth_analysis.config import ReferenceConfig
from indepth_analysis.models.euro_macro import (
    AgentResult,
    EuroMacroReport,
    ReportSection,
)
from indepth_analysis.skills.euro_macro.agents import (
    DataAgent,
    InstitutionalAgent,
    KCIFAgent,
    MediaAgent,
)
from indepth_analysis.skills.euro_macro.prompts import (
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_PROMPT,
)

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "2.0"


def default_findings_path(year: int, month: int) -> Path:
    """Return the default findings JSON path for a given year/month."""
    return Path("reports") / "euro_macro" / f"{year}-{month:02d}-findings.json"


class EuroMacroOrchestrator:
    """Runs research agents in parallel and synthesizes findings via Claude."""

    def __init__(
        self,
        config: ReferenceConfig,
        anthropic_key: str = "",
        *,
        legacy_agents: bool = False,
    ) -> None:
        self.config = config
        self.agents: list = [KCIFAgent(config)]
        if legacy_agents:
            self.agents.extend([MediaAgent(), InstitutionalAgent(), DataAgent()])
        self._anthropic_key = anthropic_key
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        """Lazy-init the Anthropic client (only needed for synthesis)."""
        if self._client is None:
            if not self._anthropic_key:
                raise RuntimeError("ANTHROPIC_API_KEY required for synthesis")
            self._client = anthropic.Anthropic(api_key=self._anthropic_key)
        return self._client

    async def run(
        self,
        year: int,
        month: int,
        model: str = "claude-sonnet-4-20250514",
        skip_update: bool = False,
    ) -> EuroMacroReport:
        """Execute the full research → synthesis pipeline."""
        agent_results = await self.collect(year, month, skip_update=skip_update)
        report = self._synthesize(agent_results, year, month, model)
        return report

    async def collect(
        self,
        year: int,
        month: int,
        skip_update: bool = False,
    ) -> list[AgentResult]:
        """Run research agents and return raw results (no synthesis)."""
        if not skip_update:
            await self._ensure_kcif_updated(year, month)

        tasks = [agent.research(year, month) for agent in self.agents]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        agent_results: list[AgentResult] = []
        for r in raw_results:
            if isinstance(r, BaseException):
                logger.error("Agent raised exception: %s", r)
            else:
                agent_results.append(r)
        return agent_results

    @staticmethod
    def save_findings(
        agent_results: list[AgentResult],
        year: int,
        month: int,
        path: Path | None = None,
    ) -> Path:
        """Serialize agent results to a JSON file with meta envelope."""
        dest = path or default_findings_path(year, month)
        dest.parent.mkdir(parents=True, exist_ok=True)

        envelope = {
            "meta": {
                "year": year,
                "month": month,
                "generated_at": datetime.now(UTC).isoformat(),
                "pipeline_version": PIPELINE_VERSION,
            },
            "agent_results": [ar.model_dump() for ar in agent_results],
        }
        dest.write_text(json.dumps(envelope, ensure_ascii=False, indent=2))
        return dest

    @staticmethod
    def load_findings(path: Path) -> tuple[list[AgentResult], int, int]:
        """Deserialize findings JSON and validate via Pydantic.

        Returns (agent_results, year, month).
        """
        raw = json.loads(path.read_text())
        meta = raw["meta"]
        year = int(meta["year"])
        month = int(meta["month"])
        agent_results = [AgentResult.model_validate(ar) for ar in raw["agent_results"]]
        return agent_results, year, month

    def synthesize_from_findings(
        self,
        agent_results: list[AgentResult],
        year: int,
        month: int,
        model: str = "claude-sonnet-4-20250514",
    ) -> EuroMacroReport:
        """Public wrapper around _synthesize for Phase 3."""
        return self._synthesize(agent_results, year, month, model)

    async def _ensure_kcif_updated(self, year: int, month: int) -> None:
        """Scrape and catalog latest KCIF reports if needed."""
        try:
            from indepth_analysis.data.kcif_client import KCIFScraper
            from indepth_analysis.db import ReferenceDB
            from indepth_analysis.models.reference import Report

            db = ReferenceDB()
            scraper = KCIFScraper()
            source = db.get_or_create_source(scraper.source_name, scraper.base_url)
            assert source.id is not None

            results = scraper.scrape_listing(year=year, month=month)
            for r in results:
                report = Report(
                    source_id=source.id,
                    external_id=r.external_id,
                    title=r.title,
                    category=r.category,
                    author=r.author,
                    published_date=r.published_date,
                    url=r.url,
                    file_name=None,
                )
                db.upsert_report(report)

            db.update_source_scraped(source.id)
            db.close()
            scraper.close()
            logger.info("KCIF catalog updated: %d reports", len(results))
        except Exception:
            logger.warning("KCIF update skipped due to error", exc_info=True)

    def _synthesize(
        self,
        agent_results: list[AgentResult],
        year: int,
        month: int,
        model: str,
    ) -> EuroMacroReport:
        """Call Claude API to synthesize findings into a report."""
        context = self._build_context(agent_results)
        total_findings = sum(len(r.findings) for r in agent_results)

        if total_findings == 0:
            return EuroMacroReport(
                year=year,
                month=month,
                title=f"{year}년 {month}월 월간 유럽 거시경제 현황",
                sections=[
                    ReportSection(
                        heading="수집 결과 없음",
                        content="리서치 에이전트에서 수집된 자료가 없습니다.",
                    )
                ],
                agent_results=agent_results,
                model_used=model,
                total_findings=0,
                generated_at=datetime.now(UTC).isoformat(),
            )

        response = self.client.messages.create(
            model=model,
            max_tokens=8192,
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": SYNTHESIS_USER_PROMPT.format(
                        year=year, month=month, context=context
                    ),
                }
            ],
        )

        body = response.content[0].text
        sections = self._parse_sections(body)

        return EuroMacroReport(
            year=year,
            month=month,
            title=f"{year}년 {month}월 월간 유럽 거시경제 현황",
            sections=sections,
            agent_results=agent_results,
            model_used=model,
            total_findings=total_findings,
            generated_at=datetime.now(UTC).isoformat(),
        )

    def _build_context(self, agent_results: list[AgentResult]) -> str:
        """Flatten all findings into a context document for the LLM."""
        parts: list[str] = []
        for ar in agent_results:
            if ar.error:
                parts.append(f"[{ar.agent_name}] 에러: {ar.error}\n")
                continue
            if not ar.findings:
                continue
            parts.append(f"### {ar.agent_name} 에이전트 수집 자료\n")
            for i, f in enumerate(ar.findings, 1):
                source_info = f"[{f.source_name}]" if f.source_name else ""
                date_info = f" ({f.published_date})" if f.published_date else ""
                parts.append(
                    f"{i}. **{f.title}** {source_info}{date_info}\n   {f.summary}\n"
                )
                if f.source_url:
                    parts.append(f"   URL: {f.source_url}\n")
            parts.append("")
        return "\n".join(parts)

    def _parse_sections(self, text: str) -> list[ReportSection]:
        """Parse markdown ## headings into ReportSection objects."""
        sections: list[ReportSection] = []
        # Split on ## headings
        pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))

        if not matches:
            # No section headings found — treat entire text as one section
            return [ReportSection(heading="보고서", content=text.strip())]

        for i, match in enumerate(matches):
            heading = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            sections.append(ReportSection(heading=heading, content=content))

        return sections
