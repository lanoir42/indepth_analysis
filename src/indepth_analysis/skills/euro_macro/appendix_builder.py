"""Appendix builder — generates supplementary report sections via LLM + deterministic data."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from indepth_analysis.models.euro_macro import AgentResult, ReportSection, ResearchFinding
from indepth_analysis.skills.euro_macro.prompts import (
    APPENDIX_COUNTRY_ANALYSIS_PROMPT,
    APPENDIX_INTRO_PROMPT,
    APPENDIX_RISK_SCENARIO_PROMPT,
    POLITICAL_LANDSCAPE_SYSTEM_PROMPT,
    POLITICAL_LANDSCAPE_USER_PROMPT,
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


def _collect_text_from_stream(stdout: str) -> str:
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


def _run_claude(prompt: str, system: str, model: str, timeout: int = 300) -> str:
    """Run a Claude CLI subprocess and return the text output."""
    proc = subprocess.Popen(
        [
            "claude", "-p", prompt,
            "--append-system-prompt", system,
            "--output-format", "stream-json",
            "--verbose",
            "--model", model,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path("/tmp")),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"Claude CLI appendix call timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Claude CLI appendix failed (exit {proc.returncode}): {stderr[:400]}"
        )
    return _collect_text_from_stream(stdout)


def _build_context_from_results(agent_results: list[AgentResult]) -> str:
    """Flatten findings into a compact context string for appendix LLM calls."""
    parts: list[str] = []
    for ar in agent_results:
        if ar.error or not ar.findings:
            continue
        parts.append(f"### {ar.agent_name}\n")
        for f in ar.findings:
            date_str = f" ({f.published_date})" if f.published_date else ""
            src = f"[{f.source_name}]" if f.source_name else ""
            parts.append(f"- **{f.title}** {src}{date_str}: {f.summary}\n")
        parts.append("")
    return "\n".join(parts)


class AppendixBuilder:
    """Builds supplementary appendix sections for the Euro Macro report."""

    def __init__(
        self,
        *,
        year: int,
        month: int,
        model: str = "claude-opus-4-20250514",
        timeout: int = 300,
    ) -> None:
        self.year = year
        self.month = month
        self.model = model
        self.timeout = timeout

    def build(self, agent_results: list[AgentResult]) -> list[ReportSection]:
        """Build all appendix sections and return them as ReportSection objects.

        Sections returned (in order):
          I.   언론 보도 요약   — deterministic from WebResearch findings
          II.  주요국별 심층 분석 — LLM generated
          III. 리스크 시나리오 — LLM generated
          IV.  출처 목록       — deterministic source index
        """
        sections: list[ReportSection] = []

        # Appendix I: media roundup (deterministic)
        media_section = self._build_media_roundup(agent_results)
        if media_section:
            sections.append(media_section)

        context = _build_context_from_results(agent_results)
        if not context.strip():
            # No context for LLM sections — skip and go straight to source index
            source_section = self._build_source_index(agent_results)
            if source_section:
                sections.append(source_section)
            return sections

        # Appendix II: country analysis (LLM)
        try:
            country_section = self._build_country_analysis(context)
            if country_section:
                sections.append(country_section)
        except Exception as exc:
            logger.warning("Appendix country analysis failed: %s", exc)

        # Appendix III: risk scenarios (LLM)
        try:
            risk_section = self._build_risk_scenarios(context)
            if risk_section:
                sections.append(risk_section)
        except Exception as exc:
            logger.warning("Appendix risk scenarios failed: %s", exc)

        # Appendix IV: source index (deterministic)
        source_section = self._build_source_index(agent_results)
        if source_section:
            sections.append(source_section)

        # Appendix V: political landscape deep-dive (LLM)
        try:
            political_section = self._build_political_landscape(agent_results)
            if political_section:
                sections.append(political_section)
        except Exception as exc:
            logger.warning("Appendix political landscape failed: %s", exc)

        return sections

    # ------------------------------------------------------------------
    # Deterministic sections
    # ------------------------------------------------------------------

    def _build_media_roundup(self, agent_results: list[AgentResult]) -> ReportSection | None:
        """Build Appendix I from WebResearch findings grouped by category."""
        web_findings: list[ResearchFinding] = []
        for ar in agent_results:
            if ar.agent_name == "WebResearch":
                web_findings = [f for f in ar.findings if not f.title.startswith("[오류]")]
                break

        if not web_findings:
            return None

        lines: list[str] = []

        # Group by category
        by_category: dict[str, list[ResearchFinding]] = {}
        for f in web_findings:
            cat = f.category or f.source_name or "기타"
            by_category.setdefault(cat, []).append(f)

        for cat, findings in by_category.items():
            lines.append(f"#### {cat}")
            lines.append("")
            for f in findings:
                date_str = f" ({f.published_date})" if f.published_date else ""
                url_str = f"\n  - 출처: {f.source_url}" if f.source_url else ""
                lines.append(f"**{f.title}**{date_str}")
                lines.append(f"{f.summary}{url_str}")
                lines.append("")

        if not lines:
            return None

        return ReportSection(
            heading=f"부록 I. 언론 보도 및 1차 출처 요약 ({self.year}년 {self.month}월)",
            content="\n".join(lines).strip(),
        )

    def _build_source_index(self, agent_results: list[AgentResult]) -> ReportSection | None:
        """Build Appendix IV: full source index."""
        lines: list[str] = []
        for ar in agent_results:
            if not ar.findings:
                continue
            lines.append(f"**{ar.agent_name}**")
            for f in ar.findings:
                if f.title.startswith("[오류]"):
                    continue
                date_str = f" ({f.published_date})" if f.published_date else ""
                url_part = f" — {f.source_url}" if f.source_url else ""
                lines.append(f"- {f.title}{date_str}{url_part}")
            lines.append("")

        if not lines:
            return None

        return ReportSection(
            heading="부록 IV. 출처 목록",
            content="\n".join(lines).strip(),
        )

    # ------------------------------------------------------------------
    # LLM-generated sections
    # ------------------------------------------------------------------

    def _build_country_analysis(self, context: str) -> ReportSection | None:
        system = (
            "당신은 유럽 거시경제 전문가입니다. "
            "수집된 자료만을 근거로 주요국별 심층 분석을 작성하세요. "
            "추측이나 자료에 없는 내용은 포함하지 마세요."
        )
        prompt = (
            APPENDIX_COUNTRY_ANALYSIS_PROMPT.format(year=self.year, month=self.month)
            + f"\n\n## 참고 자료\n\n{context}"
        )
        text = _run_claude(prompt, system, self.model, timeout=self.timeout)
        if not text.strip():
            return None
        return ReportSection(
            heading=f"부록 II. 주요국별 심층 분석 ({self.year}년 {self.month}월)",
            content=text.strip(),
        )

    def _build_risk_scenarios(self, context: str) -> ReportSection | None:
        system = (
            "당신은 유럽 거시경제 리스크 분석 전문가입니다. "
            "수집된 자료만을 근거로 시나리오 분석을 작성하세요. "
            "추측이나 자료에 없는 내용은 포함하지 마세요."
        )
        prompt = (
            APPENDIX_RISK_SCENARIO_PROMPT.format(year=self.year, month=self.month)
            + f"\n\n## 참고 자료\n\n{context}"
        )
        text = _run_claude(prompt, system, self.model, timeout=self.timeout)
        if not text.strip():
            return None
        return ReportSection(
            heading=f"부록 III. 리스크 시나리오 분석 ({self.year}년 {self.month}월)",
            content=text.strip(),
        )

    def _build_political_landscape(
        self, agent_results: list[AgentResult]
    ) -> ReportSection | None:
        """Build Appendix V: European political landscape deep-dive.

        Uses WebResearch political category findings as primary context,
        supplemented by all other agent findings.
        """
        # Collect political-category findings first (higher priority)
        political_categories = {"유럽 정치지형 (언론)", "유럽 정치지형 (연구기관)", "EU 정치"}
        political_lines: list[str] = []
        other_lines: list[str] = []

        for ar in agent_results:
            for f in ar.findings:
                if f.title.startswith("[오류]"):
                    continue
                date_str = f" ({f.published_date})" if f.published_date else ""
                src = f.source_name or ar.agent_name
                url_str = f"\n  URL: {f.source_url}" if f.source_url else ""
                line = f"- [{src}] **{f.title}**{date_str}: {f.summary}{url_str}"

                cat = f.category or f.source_name or ""
                if cat in political_categories:
                    political_lines.append(line)
                else:
                    other_lines.append(line)

        if not political_lines and not other_lines:
            return None

        # Build context: political findings first, then general macro context
        context_parts: list[str] = []
        if political_lines:
            context_parts.append("### 정치지형 전문 자료 (언론·연구기관)")
            context_parts.extend(political_lines)
            context_parts.append("")
        if other_lines:
            context_parts.append("### 거시경제·시장 관련 자료 (정치 영향 분석에 활용)")
            # Limit general context to avoid token overflow
            context_parts.extend(other_lines[:60])
            context_parts.append("")

        context = "\n".join(context_parts)
        prompt = POLITICAL_LANDSCAPE_USER_PROMPT.format(
            year=self.year, month=self.month, context=context
        )
        text = _run_claude(
            prompt, POLITICAL_LANDSCAPE_SYSTEM_PROMPT, self.model, timeout=self.timeout
        )
        if not text.strip():
            return None
        return ReportSection(
            heading=f"부록 V. 유럽 정치지형 심층 분석 ({self.year}년 {self.month}월)",
            content=text.strip(),
        )
