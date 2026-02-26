"""Tests for the Euro Macro report skill."""

import json

import pytest

from indepth_analysis.models.euro_macro import (
    AgentResult,
    EuroMacroReport,
    ReportSection,
    ResearchFinding,
)
from indepth_analysis.skills.base import BaseResearchAgent
from indepth_analysis.skills.euro_macro.orchestrator import (
    EuroMacroOrchestrator,
    default_findings_path,
)
from indepth_analysis.skills.euro_macro.prompts import (
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_PROMPT,
)
from indepth_analysis.skills.euro_macro.renderer import render_markdown

# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------


class TestResearchFinding:
    def test_defaults(self):
        f = ResearchFinding(title="Test", summary="A summary")
        assert f.title == "Test"
        assert f.summary == "A summary"
        assert f.source_url is None
        assert f.source_name == ""
        assert f.relevance_score == 0.0
        assert f.category == ""

    def test_full_construction(self):
        f = ResearchFinding(
            title="ECB Decision",
            summary="Rate held steady",
            source_url="https://ecb.europa.eu/decision",
            source_name="ECB",
            published_date="2026-02-15",
            relevance_score=0.85,
            category="통화정책",
        )
        assert f.source_name == "ECB"
        assert f.relevance_score == 0.85


class TestAgentResult:
    def test_empty(self):
        ar = AgentResult(agent_name="Test")
        assert ar.agent_name == "Test"
        assert ar.findings == []
        assert ar.search_queries == []
        assert ar.error is None

    def test_with_error(self):
        ar = AgentResult(agent_name="Test", error="connection failed")
        assert ar.error == "connection failed"

    def test_with_findings(self):
        findings = [
            ResearchFinding(title="A", summary="a"),
            ResearchFinding(title="B", summary="b"),
        ]
        ar = AgentResult(
            agent_name="Media",
            findings=findings,
            search_queries=["q1", "q2"],
        )
        assert len(ar.findings) == 2
        assert len(ar.search_queries) == 2


class TestEuroMacroReport:
    def test_empty_report(self):
        report = EuroMacroReport(
            year=2026,
            month=2,
            title="2026년 2월 월간 유럽 거시경제 현황",
        )
        assert report.year == 2026
        assert report.month == 2
        assert report.sections == []
        assert report.total_findings == 0

    def test_full_report(self):
        report = EuroMacroReport(
            year=2026,
            month=2,
            title="2026년 2월 월간 유럽 거시경제 현황",
            sections=[
                ReportSection(heading="1. 통화정책", content="ECB held rates."),
            ],
            model_used="claude-sonnet-4-20250514",
            total_findings=10,
            generated_at="2026-02-26T12:00:00+00:00",
        )
        assert len(report.sections) == 1
        assert report.model_used == "claude-sonnet-4-20250514"
        assert report.total_findings == 10


# ---------------------------------------------------------------------------
# Base agent tests
# ---------------------------------------------------------------------------


class TestBaseResearchAgent:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseResearchAgent()

    def test_subclass(self):
        class DummyAgent(BaseResearchAgent):
            name = "dummy"

            async def research(self, year: int, month: int) -> AgentResult:
                return AgentResult(agent_name=self.name)

        agent = DummyAgent()
        assert agent.name == "dummy"


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------


class TestOrchestratorParseSections:
    def setup_method(self):
        self.orch = EuroMacroOrchestrator.__new__(EuroMacroOrchestrator)

    def test_parse_sections_normal(self):
        text = "## 1. 통화정책\n\nECB held rates.\n\n## 2. 경제성장\n\nGDP grew 0.3%.\n"
        sections = self.orch._parse_sections(text)
        assert len(sections) == 2
        assert sections[0].heading == "1. 통화정책"
        assert "ECB held rates" in sections[0].content
        assert sections[1].heading == "2. 경제성장"

    def test_parse_sections_no_headings(self):
        text = "Just some text without headings."
        sections = self.orch._parse_sections(text)
        assert len(sections) == 1
        assert sections[0].heading == "보고서"

    def test_parse_sections_single(self):
        text = "## Summary\n\nContent here."
        sections = self.orch._parse_sections(text)
        assert len(sections) == 1
        assert sections[0].heading == "Summary"


class TestOrchestratorBuildContext:
    def setup_method(self):
        self.orch = EuroMacroOrchestrator.__new__(EuroMacroOrchestrator)

    def test_build_context_with_findings(self):
        results = [
            AgentResult(
                agent_name="Media",
                findings=[
                    ResearchFinding(
                        title="News Article",
                        summary="Summary text",
                        source_name="Reuters",
                        source_url="https://reuters.com/article",
                    ),
                ],
                search_queries=["q1"],
            ),
        ]
        context = self.orch._build_context(results)
        assert "Media" in context
        assert "News Article" in context
        assert "Reuters" in context

    def test_build_context_with_error(self):
        results = [
            AgentResult(
                agent_name="Data",
                error="timeout",
                search_queries=["q1"],
            ),
        ]
        context = self.orch._build_context(results)
        assert "에러" in context
        assert "timeout" in context


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------


class TestRenderer:
    def test_render_markdown_basic(self):
        report = EuroMacroReport(
            year=2026,
            month=2,
            title="2026년 2월 월간 유럽 거시경제 현황",
            sections=[
                ReportSection(heading="1. 통화정책", content="ECB held rates."),
                ReportSection(heading="2. 경제성장", content="GDP grew."),
            ],
            agent_results=[
                AgentResult(
                    agent_name="KCIF",
                    findings=[
                        ResearchFinding(
                            title="KCIF Report",
                            summary="Summary",
                            source_url="https://kcif.or.kr/report/1",
                            published_date="2026-02-10",
                        ),
                    ],
                ),
            ],
            model_used="claude-sonnet-4-20250514",
            total_findings=1,
            generated_at="2026-02-26T12:00:00+00:00",
        )
        md = render_markdown(report)

        # Title
        assert "# 2026년 2월 월간 유럽 거시경제 현황" in md
        # Table of contents
        assert "## 목차" in md
        assert "1. 통화정책" in md
        # Sections
        assert "ECB held rates." in md
        assert "GDP grew." in md
        # Source appendix
        assert "## 참고 자료" in md
        assert "KCIF Report" in md
        # Metadata
        assert "claude-sonnet-4-20250514" in md

    def test_render_empty_report(self):
        report = EuroMacroReport(
            year=2026,
            month=2,
            title="2026년 2월 월간 유럽 거시경제 현황",
            generated_at="2026-02-26T00:00:00+00:00",
        )
        md = render_markdown(report)
        assert "# 2026년 2월" in md
        assert "수집 자료: 0건" in md


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_system_prompt_has_sections(self):
        assert "통화정책" in SYNTHESIS_SYSTEM_PROMPT
        assert "경제성장" in SYNTHESIS_SYSTEM_PROMPT
        assert "인플레이션" in SYNTHESIS_SYSTEM_PROMPT

    def test_user_prompt_has_placeholders(self):
        assert "{year}" in SYNTHESIS_USER_PROMPT
        assert "{month}" in SYNTHESIS_USER_PROMPT
        assert "{context}" in SYNTHESIS_USER_PROMPT

    def test_user_prompt_formats(self):
        result = SYNTHESIS_USER_PROMPT.format(
            year=2026, month=2, context="test context"
        )
        assert "2026년 2월" in result
        assert "test context" in result


# ---------------------------------------------------------------------------
# Findings I/O tests
# ---------------------------------------------------------------------------


class TestFindingsIO:
    def _sample_results(self) -> list[AgentResult]:
        return [
            AgentResult(
                agent_name="KCIF",
                findings=[
                    ResearchFinding(
                        title="ECB Rate Decision",
                        summary="Rates held steady.",
                        source_url="https://kcif.or.kr/report/1",
                        source_name="KCIF",
                        published_date="2026-02-15",
                        relevance_score=0.85,
                    ),
                ],
                search_queries=["유럽 경제 전망"],
            ),
        ]

    def test_default_findings_path(self):
        path = default_findings_path(2026, 2)
        assert path.name == "2026-02-findings.json"
        assert "euro_macro" in str(path)

    def test_save_load_roundtrip(self, tmp_path):
        results = self._sample_results()
        dest = tmp_path / "findings.json"

        saved = EuroMacroOrchestrator.save_findings(results, 2026, 2, path=dest)
        assert saved.exists()

        loaded_results, year, month = EuroMacroOrchestrator.load_findings(saved)
        assert year == 2026
        assert month == 2
        assert len(loaded_results) == 1
        assert loaded_results[0].agent_name == "KCIF"
        assert len(loaded_results[0].findings) == 1
        assert loaded_results[0].findings[0].title == "ECB Rate Decision"
        assert loaded_results[0].findings[0].relevance_score == 0.85

    def test_save_creates_parent_dirs(self, tmp_path):
        dest = tmp_path / "deep" / "nested" / "findings.json"
        results = self._sample_results()
        saved = EuroMacroOrchestrator.save_findings(results, 2026, 2, path=dest)
        assert saved.exists()

    def test_save_meta_envelope(self, tmp_path):
        dest = tmp_path / "findings.json"
        results = self._sample_results()
        EuroMacroOrchestrator.save_findings(results, 2026, 2, path=dest)

        raw = json.loads(dest.read_text())
        assert "meta" in raw
        assert raw["meta"]["year"] == 2026
        assert raw["meta"]["month"] == 2
        assert "generated_at" in raw["meta"]
        assert raw["meta"]["pipeline_version"] == "2.0"
        assert "agent_results" in raw

    def test_load_validation_error_on_bad_data(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(
            json.dumps(
                {
                    "meta": {"year": 2026, "month": 2},
                    "agent_results": [{"invalid_field": "oops"}],
                }
            )
        )
        with pytest.raises(Exception):
            EuroMacroOrchestrator.load_findings(bad_file)

    def test_load_missing_meta_raises(self, tmp_path):
        bad_file = tmp_path / "no_meta.json"
        bad_file.write_text(json.dumps({"agent_results": []}))
        with pytest.raises(KeyError):
            EuroMacroOrchestrator.load_findings(bad_file)


# ---------------------------------------------------------------------------
# Orchestrator init tests
# ---------------------------------------------------------------------------


class TestOrchestratorInit:
    def test_default_has_only_kcif(self):
        from indepth_analysis.config import ReferenceConfig

        config = ReferenceConfig()
        orch = EuroMacroOrchestrator(config)
        assert len(orch.agents) == 1
        assert orch.agents[0].name == "KCIF"

    def test_legacy_agents_adds_all_four(self):
        from indepth_analysis.config import ReferenceConfig

        config = ReferenceConfig()
        orch = EuroMacroOrchestrator(config, legacy_agents=True)
        assert len(orch.agents) == 4
        names = [a.name for a in orch.agents]
        assert "KCIF" in names
