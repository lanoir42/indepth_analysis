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


def test_codex_quota_message_is_classified_symmetrically_with_claude(monkeypatch,tmp_path):
    """W-a1: a Codex usage-limit event must cool Codex down the same way a Claude
    quota refusal cools Claude down — before this fix it fell through to the
    generic 'provider_error' and never triggered block_provider()."""
    import pytest
    with pytest.raises(transport.ReportCLIError,match='quota'):
        transport._parse('codex',json.dumps({'type':'turn.failed','error':{'message':'Rate limit exceeded (429)'}}),{})


def test_codex_provider_error_without_quota_wording_stays_generic():
    import pytest
    with pytest.raises(transport.ReportCLIError,match='provider_error'):
        transport._parse('codex',json.dumps({'type':'turn.failed','error':{'message':'internal server error'}}),{})


def test_codex_quota_cools_down_via_complete(monkeypatch,tmp_path):
    import sqlite3,pytest
    monkeypatch.setattr(transport,'LEDGER',tmp_path/'ledger.sqlite')
    quota_event=json.dumps({'type':'turn.failed','error':{'message':'usage_limit_reached'}})
    run=Mock(side_effect=[SimpleNamespace(returncode=1,stdout='not json at all'),  # claude: invalid_envelope
                         SimpleNamespace(returncode=1,stdout=quota_event),        # codex: quota
                         SimpleNamespace(returncode=1,stdout='not json at all')]) # 2nd call claude: invalid_envelope
    monkeypatch.setattr(transport,'_run',run)
    with pytest.raises(transport.ReportCLIError):
        transport.complete('synthetic')
    with sqlite3.connect(transport.LEDGER) as conn:
        assert conn.execute(
            "SELECT count(*) FROM attempts WHERE provider='codex' AND status='failed' AND error_code='quota'"
        ).fetchone()[0]==1
    # Second call: codex should now be skipped (cooled down) rather than retried
    # (claude fails again so the loop actually reaches the codex slot).
    with pytest.raises(transport.ReportCLIError):
        transport.complete('synthetic')
    assert [c.args[0][0] for c in run.call_args_list]==['claude','codex','claude']
    with sqlite3.connect(transport.LEDGER) as conn:
        assert conn.execute("SELECT count(*) FROM attempts WHERE status='skipped'").fetchone()[0]==1


def test_caller_routing_is_legacy_by_default_and_records_route_fields(monkeypatch,tmp_path):
    """W-a1: passing caller= must not change the provider order while the global
    switch stays at its default (claude) — and it must record route metadata."""
    import sqlite3
    monkeypatch.delenv('INDEPTH_REPORT_PRIMARY',raising=False)
    monkeypatch.setattr(transport,'LEDGER',tmp_path/'ledger.sqlite')
    monkeypatch.setenv('INDEPTH_PARITY_SHADOW','0')  # isolate this test from capture side-effects
    ok='\n'.join(json.dumps(e) for e in [
        {'type':'item.completed','item':{'type':'agent_message','text':'Synthetic'}},
        {'type':'turn.completed','usage':{'input_tokens':12}}])
    run=Mock(return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'result':'Synthetic'})))
    monkeypatch.setattr(transport,'_run',run)
    result=transport.complete('synthetic',tier='haiku',caller='kcif.update_topic')
    assert result=='Synthetic'
    assert run.call_args.args[0][0]=='claude'  # legacy order preserved
    with sqlite3.connect(transport.LEDGER) as conn:
        row=conn.execute("SELECT route_mode,decision_reason FROM attempts WHERE status='success'").fetchone()
        assert row==('claude','global_claude')


def test_caller_routing_writes_capture_on_success(monkeypatch,tmp_path):
    monkeypatch.delenv('INDEPTH_REPORT_PRIMARY',raising=False)
    monkeypatch.setattr(transport,'LEDGER',tmp_path/'ledger.sqlite')
    monkeypatch.setenv('BRIEFING_PARITY_DIR',str(tmp_path/'parity'))
    monkeypatch.delenv('INDEPTH_PARITY_SHADOW',raising=False)  # default ON
    run=Mock(return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'result':'Synthetic'})))
    monkeypatch.setattr(transport,'_run',run)
    transport.complete('the exact prompt sent',tier='haiku',caller='kcif.update_topic')
    captured=list((tmp_path/'parity'/'_captures'/'kcif.update_topic').glob('*.json'))
    assert len(captured)==1
    data=json.loads(captured[0].read_text(encoding='utf-8'))
    assert data['prompt']=='the exact prompt sent'
    assert data['caller']=='kcif.update_topic'
