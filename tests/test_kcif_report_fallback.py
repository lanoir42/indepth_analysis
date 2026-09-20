import json
from types import SimpleNamespace
from unittest.mock import Mock
from indepth_analysis import report_cli as transport
from indepth_analysis.kcif import llm


def test_invalid_primary_json_falls_back_and_required_keys_survive(monkeypatch,tmp_path):
    monkeypatch.setenv('INDEPTH_REPORT_FALLBACK','1')
    monkeypatch.setattr(transport,'LEDGER',tmp_path/'ledger.sqlite')
    output='\n'.join(json.dumps(e) for e in [
        {'type':'item.completed','item':{'type':'agent_message','text':'{"topics":["synthetic"]}'}},
        {'type':'turn.completed','usage':{'input_tokens':12}}])
    run=Mock(side_effect=[SimpleNamespace(returncode=0,stdout=json.dumps({'result':'{"wrong":true}'})),
                         SimpleNamespace(returncode=0,stdout=output)])
    monkeypatch.setattr(transport,'_run',run)
    assert llm.call_json('synthetic',system='JSON',required_keys=('topics',))=={'topics':['synthetic']}
    assert run.call_count==2
    assert 'gpt-5.6-luna' in run.call_args.args[0]


def test_both_fail_leave_none_for_watermark_contract(monkeypatch,tmp_path):
    monkeypatch.setenv('INDEPTH_REPORT_FALLBACK','1')
    monkeypatch.setattr(transport,'LEDGER',tmp_path/'ledger.sqlite')
    monkeypatch.setattr(transport,'_run',Mock(side_effect=FileNotFoundError))
    assert llm.call_json('synthetic',system='JSON',required_keys=('topics',)) is None


def test_quota_exit_cools_down_across_calls(monkeypatch,tmp_path):
    import sqlite3
    monkeypatch.setattr(transport,'LEDGER',tmp_path/'ledger.sqlite')
    output='\n'.join(json.dumps(e) for e in [
        {'type':'item.completed','item':{'type':'agent_message','text':'Synthetic'}},
        {'type':'turn.completed','usage':{'input_tokens':12}}])
    run=Mock(side_effect=[SimpleNamespace(returncode=1,stdout="You've hit your usage limit"),
                         SimpleNamespace(returncode=0,stdout=output),SimpleNamespace(returncode=0,stdout=output)])
    monkeypatch.setattr(transport,'_run',run)
    assert transport.complete('synthetic')=='Synthetic'
    assert transport.complete('synthetic')=='Synthetic'
    assert [c.args[0][0] for c in run.call_args_list]==['claude','codex','codex']
    with sqlite3.connect(transport.LEDGER) as conn:
        assert conn.execute("SELECT count(*) FROM attempts WHERE status='skipped'").fetchone()[0]==1


def test_invalid_codex_item_is_transport_error():
    import pytest
    with pytest.raises(transport.ReportCLIError,match='invalid_envelope'):
        transport._parse('codex','{"type":"item.completed","item":123}',{})
