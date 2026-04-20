"""Orchestrator — dispatches agents in parallel and synthesizes via Claude CLI."""

import asyncio
import json
import logging
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from indepth_analysis.models.dev_welfare import DevWelfareReport
from indepth_analysis.models.euro_macro import AgentResult, ReportSection
from indepth_analysis.skills.dev_welfare.agents import (
    DevWelfareMediaAgent,
    JournalAgent,
    KIHASAAgent,
    KOICAAgent,
    LegislationAgent,
    OECDAgent,
)
from indepth_analysis.skills.dev_welfare.prompts import (
    MONTHLY_SYSTEM_PROMPT,
    MONTHLY_USER_PROMPT,
    WEEKLY_SYSTEM_PROMPT,
    WEEKLY_USER_PROMPT,
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

PIPELINE_VERSION = "1.0"


def default_findings_path(
    year: int, month: int, week: int | None = None
) -> Path:
    if week is not None:
        return (
            Path("reports")
            / "dev_welfare"
            / f"{year}-{month:02d}-W{week}-findings.json"
        )
    return Path("reports") / "dev_welfare" / f"{year}-{month:02d}-findings.json"


def _current_week_of_month() -> int:
    """Return the current ISO week number within the month (1-5)."""
    today = datetime.now(UTC).date()
    first_day = today.replace(day=1)
    return (today.day + first_day.weekday()) // 7 + 1


class DevWelfareOrchestrator:
    """Runs research agents in parallel and synthesizes findings via Claude CLI."""

    def __init__(self) -> None:
        self.agents = [
            KOICAAgent(),
            KIHASAAgent(),
            LegislationAgent(),
            JournalAgent(),
            DevWelfareMediaAgent(),
            OECDAgent(),
        ]

    async def run(
        self,
        year: int,
        month: int,
        model: str = "claude-sonnet-4-20250514",
        report_type: str = "weekly",
        week: int | None = None,
    ) -> DevWelfareReport:
        """Execute the full research -> synthesis pipeline."""
        agent_results = await self.collect(year, month)
        report = self._synthesize(
            agent_results, year, month, model, report_type, week
        )
        return report

    async def collect(self, year: int, month: int) -> list[AgentResult]:
        """Run all research agents and return raw results."""
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
        week: int | None = None,
        path: Path | None = None,
    ) -> Path:
        """Serialize agent results to a JSON file with meta envelope."""
        dest = path or default_findings_path(year, month, week)
        dest.parent.mkdir(parents=True, exist_ok=True)

        envelope = {
            "meta": {
                "year": year,
                "month": month,
                "week": week,
                "generated_at": datetime.now(UTC).isoformat(),
                "pipeline_version": PIPELINE_VERSION,
            },
            "agent_results": [ar.model_dump() for ar in agent_results],
        }
        dest.write_text(json.dumps(envelope, ensure_ascii=False, indent=2))
        return dest

    @staticmethod
    def load_findings(
        path: Path,
    ) -> tuple[list[AgentResult], int, int, int | None]:
        """Deserialize findings JSON and validate via Pydantic.

        Returns (agent_results, year, month, week).
        """
        raw = json.loads(path.read_text())
        meta = raw["meta"]
        year = int(meta["year"])
        month = int(meta["month"])
        week = meta.get("week")
        if week is not None:
            week = int(week)
        agent_results = [
            AgentResult.model_validate(ar) for ar in raw["agent_results"]
        ]
        return agent_results, year, month, week

    def synthesize_from_findings(
        self,
        agent_results: list[AgentResult],
        year: int,
        month: int,
        model: str = "claude-sonnet-4-20250514",
        report_type: str = "weekly",
        week: int | None = None,
    ) -> DevWelfareReport:
        """Public wrapper around _synthesize for external callers."""
        return self._synthesize(
            agent_results, year, month, model, report_type, week
        )

    def _synthesize(
        self,
        agent_results: list[AgentResult],
        year: int,
        month: int,
        model: str,
        report_type: str = "weekly",
        week: int | None = None,
    ) -> DevWelfareReport:
        """Call Claude CLI to synthesize findings into a report."""
        context = self._build_context(agent_results)
        total_findings = sum(len(r.findings) for r in agent_results)

        if week is None and report_type == "weekly":
            week = _current_week_of_month()

        if total_findings == 0:
            title = self._build_title(year, month, week, report_type)
            return DevWelfareReport(
                year=year,
                month=month,
                week=week,
                title=title,
                report_type=report_type,
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

        if report_type == "monthly":
            system_prompt = MONTHLY_SYSTEM_PROMPT
            user_prompt = MONTHLY_USER_PROMPT.format(
                year=year, month=month, context=context
            )
        else:
            system_prompt = WEEKLY_SYSTEM_PROMPT
            user_prompt = WEEKLY_USER_PROMPT.format(
                year=year, month=month, week=week, context=context
            )

        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

        if model not in _ALLOWED_MODELS:
            raise ValueError(
                f"Model {model!r} not in allowed list: {sorted(_ALLOWED_MODELS)}"
            )

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
            timeout=300,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Claude CLI failed (exit {result.returncode}): {result.stderr}"
            )

        body = result.stdout.strip()
        sections = self._parse_sections(body)
        title = self._build_title(year, month, week, report_type)

        return DevWelfareReport(
            year=year,
            month=month,
            week=week,
            title=title,
            report_type=report_type,
            sections=sections,
            agent_results=agent_results,
            model_used=model,
            total_findings=total_findings,
            generated_at=datetime.now(UTC).isoformat(),
        )

    def _build_title(
        self,
        year: int,
        month: int,
        week: int | None,
        report_type: str,
    ) -> str:
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        if report_type == "weekly" and week is not None:
            return (
                f"[{ts}] {year}년 {month}월 {week}주차 "
                f"국제개발·사회복지 주간 브리핑"
            )
        if report_type == "monthly":
            return f"[{ts}] {year}년 {month}월 국제개발·사회복지 월간 분석"
        return f"[{ts}] {year}년 {month}월 국제개발·사회복지 보고서"

    def _build_context(self, agent_results: list[AgentResult]) -> str:
        """Flatten all findings into a context document for the LLM.

        URLs are omitted to keep the context compact and avoid encoding
        issues with the CLI subprocess.  Source attribution is preserved
        via source_name and published_date.
        """
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
                    f"{i}. **{f.title}** {source_info}{date_info}\n"
                    f"   {f.summary}\n"
                )
            parts.append("")
        return "\n".join(parts)

    def _parse_sections(self, text: str) -> list[ReportSection]:
        """Parse markdown ## headings into ReportSection objects."""
        sections: list[ReportSection] = []
        pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
        matches = list(pattern.finditer(text))

        if not matches:
            return [ReportSection(heading="보고서", content=text.strip())]

        for i, match in enumerate(matches):
            heading = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[start:end].strip()
            sections.append(ReportSection(heading=heading, content=content))

        return sections
