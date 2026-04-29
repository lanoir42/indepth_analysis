"""Orchestrator — dispatches agents in parallel and synthesizes via Claude CLI."""

import asyncio
import json
import logging
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from indepth_analysis.config import ReferenceConfig
from indepth_analysis.models.euro_macro import (
    AgentResult,
    EuroMacroReport,
    ReportSection,
)
from indepth_analysis.skills.euro_macro.agents import (
    DataAgent,
    ForexFactoryAgent,
    InstitutionalAgent,
    KCIFAgent,
    MediaAgent,
)
from indepth_analysis.skills.euro_macro.macro_sections import (
    MacroSectionsBuilder,
)
from indepth_analysis.skills.euro_macro.prompts import (
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_PROMPT,
)

logger = logging.getLogger(__name__)

_ALLOWED_MODELS = frozenset(
    {
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6-20260401",
        "claude-opus-4-6-20260401",
    }
)

PIPELINE_VERSION = "2.0"


def default_findings_path(year: int, month: int) -> Path:
    """Return the default findings JSON path for a given year/month."""
    return Path("reports") / "euro_macro" / f"{year}-{month:02d}-findings.json"


class EuroMacroOrchestrator:
    """Runs research agents in parallel and synthesizes findings via Claude CLI."""

    def __init__(
        self,
        config: ReferenceConfig,
        *,
        legacy_agents: bool = False,
        no_macro: bool = False,
        force_refresh: bool = False,
        alert_abs_surprise: float | None = None,
    ) -> None:
        self.config = config
        self.no_macro = no_macro
        self.force_refresh = force_refresh
        self.alert_abs_surprise = alert_abs_surprise
        self.agents: list = [KCIFAgent(config)]
        if not no_macro:
            self.agents.append(ForexFactoryAgent(force_refresh=force_refresh))
        if legacy_agents:
            self.agents.extend([MediaAgent(), InstitutionalAgent(), DataAgent()])

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
        await self._dispatch_telegram_alerts(agent_results)
        return report

    async def _dispatch_telegram_alerts(
        self, agent_results: list[AgentResult]
    ) -> None:
        """Send sigma-alert notifications via Telegram (best-effort, non-fatal)."""
        ff_result, _ = self._extract_ff_result(agent_results)
        if ff_result is None:
            return
        sigma_alerts_data = (ff_result.extra or {}).get("sigma_alerts", [])
        if not sigma_alerts_data:
            return
        try:
            from bgilib.macro.storage import MacroStore

            from indepth_analysis.skills.euro_macro.macro_telegram import (
                _send_sigma_alerts_from_dicts,
            )

            store = MacroStore(Path("data/macro_calendar.db"))
            sent = await asyncio.to_thread(
                _send_sigma_alerts_from_dicts,
                sigma_alerts_data,
                store=store,
            )
            if sent:
                logger.info("Telegram: %d sigma alerts sent", sent)
        except Exception as exc:
            logger.warning("Telegram dispatch failed (non-fatal): %s", exc)

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

    @staticmethod
    def _extract_ff_result(
        agent_results: list[AgentResult],
    ) -> tuple[AgentResult | None, list[AgentResult]]:
        """Pop the ForexFactory AgentResult from the list.

        Returns (ff_result, remaining_results). The remaining list excludes
        the FF entry so its non-prose data does not pollute the LLM context.
        """
        ff_result: AgentResult | None = None
        remaining: list[AgentResult] = []
        for ar in agent_results:
            if ar.agent_name == "ForexFactory" and ff_result is None:
                ff_result = ar
            else:
                remaining.append(ar)
        return ff_result, remaining

    def _synthesize(
        self,
        agent_results: list[AgentResult],
        year: int,
        month: int,
        model: str,
    ) -> EuroMacroReport:
        """Call Claude CLI (claude code max) to synthesize findings into a report."""
        ff_result, prose_results = self._extract_ff_result(agent_results)

        context = self._build_context(prose_results)
        total_findings = sum(len(r.findings) for r in prose_results)

        # Build deterministic macro sections + LLM digest (only when FF available)
        builder: MacroSectionsBuilder | None = None
        macro_sections: list[ReportSection] = []
        if ff_result is not None:
            builder = MacroSectionsBuilder(year=year, month=month)
            macro_sections = builder.build(ff_result)
            digest = builder.build_llm_context_digest(ff_result)
            if digest:
                context = (
                    "### ForexFactory 거시 캘린더 (참고용)\n"
                    f"{digest}\n\n"
                    + context
                )

        if total_findings == 0:
            base_sections: list[ReportSection] = [
                ReportSection(
                    heading="수집 결과 없음",
                    content="리서치 에이전트에서 수집된 자료가 없습니다.",
                )
            ]
            base_sections.extend(macro_sections)
            return EuroMacroReport(
                year=year,
                month=month,
                title=f"{year}년 {month}월 월간 유럽 거시경제 현황",
                sections=base_sections,
                agent_results=agent_results,
                model_used=model,
                total_findings=0,
                generated_at=datetime.now(UTC).isoformat(),
            )

        prompt = (
            f"<system>\n{SYNTHESIS_SYSTEM_PROMPT}\n</system>\n\n"
            + SYNTHESIS_USER_PROMPT.format(year=year, month=month, context=context)
        )

        if model not in _ALLOWED_MODELS:
            raise ValueError(
                f"Model {model!r} not in allowed list: {sorted(_ALLOWED_MODELS)}"
            )

        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Claude CLI failed (exit {result.returncode}): {result.stderr}"
            )

        body = result.stdout.strip()
        sections = self._parse_sections(body)
        sections.extend(macro_sections)

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
