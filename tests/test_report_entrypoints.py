import asyncio
from unittest.mock import Mock, AsyncMock
from indepth_analysis import report_cli as transport
from indepth_analysis.skills.euro_macro import appendix_builder
from indepth_analysis.skills.euro_macro.weekly_brief.orchestrator import WeeklyBriefOrchestrator
from indepth_analysis.skills.euro_macro.masterclass.orchestrator import MasterclassOrchestrator
from indepth_analysis.skills.euro_macro.agents.web_research_agent import WebResearchAgent, WEB_TOPICS
from indepth_analysis.skills.issue_track import orchestrator as issue
from indepth_analysis.skills.issue_track.agents.claude_search import issue_web_search
from indepth_analysis.skills.dev_welfare.agents.claude_search import claude_web_search


def test_stage_entrypoints_route_without_live_inference(monkeypatch):
    monkeypatch.setenv('INDEPTH_REPORT_FALLBACK','1')
    sync=Mock(return_value=transport.ReportOutput('[]','codex','gpt-5.6-terra'))
    async_call=AsyncMock(return_value='[]')
    monkeypatch.setattr(transport,'complete',sync)
    monkeypatch.setattr(transport,'acomplete',async_call)
    weekly=WeeklyBriefOrchestrator.__new__(WeeklyBriefOrchestrator);weekly.model='sonnet'
    master=MasterclassOrchestrator.__new__(MasterclassOrchestrator);master.model='sonnet'
    assert weekly._call_claude('prompt','system',30,'test')=='[]'
    assert master._exec_claude('prompt','system',30,'test')=='[]'
    assert appendix_builder._run_claude('prompt','system','sonnet')=='[]'
    assert issue_web_search('prompt')==[]
    assert claude_web_search('test',2026,9,'test')==[]
    agent=WebResearchAgent()
    assert asyncio.run(agent._research_topic(WEB_TOPICS[0],2026,9,asyncio.Semaphore(1)))==[]
    assert async_call.call_args.kwargs['timeout']==agent.timeout_per_topic
    assert async_call.call_args.kwargs['web'] is True
    assert sync.call_count==5


def test_slug_no_duplicate_discarded_search(monkeypatch):
    monkeypatch.setenv('INDEPTH_REPORT_FALLBACK','1')
    complete=Mock(return_value='synthetic-topic')
    monkeypatch.setattr(transport,'complete',complete)
    unused=Mock(side_effect=AssertionError('duplicate search'))
    monkeypatch.setattr(issue,'issue_web_search',unused)
    assert issue._extract_slug('Synthetic topic')=='synthetic-topic'
    complete.assert_called_once()


def test_versioned_claude_mapping():
    assert transport.tier_of('claude-haiku-4-5-20251001')=='haiku'
    assert transport.tier_of('claude-sonnet-5')=='sonnet'


def test_synthesis_empty_and_nonempty_actual_model(monkeypatch):
    from indepth_analysis.skills.euro_macro.orchestrator import EuroMacroOrchestrator
    from indepth_analysis.skills.dev_welfare.orchestrator import DevWelfareOrchestrator
    from indepth_analysis.models.euro_macro import AgentResult, ResearchFinding
    monkeypatch.setenv('INDEPTH_REPORT_FALLBACK','1')
    call=Mock(return_value=transport.ReportOutput('## Findings\nSynthetic evidence.','codex','gpt-5.6-terra'))
    monkeypatch.setattr(transport,'complete',call)
    monkeypatch.setattr(appendix_builder.AppendixBuilder, 'build', Mock(return_value=[]))
    findings=[AgentResult(agent_name='synthetic',findings=[ResearchFinding(title='Synthetic',summary='Evidence')])]
    for cls in (EuroMacroOrchestrator,DevWelfareOrchestrator):
        obj=cls.__new__(cls)
        empty=obj._synthesize([],2026,9,'claude-sonnet-4-20250514')
        assert empty.total_findings==0
        report=obj._synthesize(findings,2026,9,'claude-sonnet-4-20250514')
        assert report.model_used=='gpt-5.6-terra'
        assert any('Synthetic evidence.' in section.content for section in report.sections)
    assert call.call_count==2


def test_masterclass_does_not_multiply_transport_attempts(monkeypatch):
    import pytest
    monkeypatch.setenv('INDEPTH_REPORT_FALLBACK','1')
    call=Mock(side_effect=transport.ReportCLIError('unavailable'))
    monkeypatch.setattr(transport,'complete',call)
    obj=MasterclassOrchestrator.__new__(MasterclassOrchestrator);obj.model='sonnet'
    with pytest.raises(transport.ReportCLIError):
        obj._call_claude('prompt','system',30,'test',retries=4)
    call.assert_called_once()
