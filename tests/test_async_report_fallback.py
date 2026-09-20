import asyncio
import json
from unittest.mock import AsyncMock
from indepth_analysis import report_cli as transport
from indepth_analysis.skills.euro_macro.monthly_brief import research


def test_monthly_failure_never_writes_final_output(monkeypatch,tmp_path):
    monkeypatch.setenv('INDEPTH_REPORT_FALLBACK','1')
    monkeypatch.setattr(transport,'acomplete',AsyncMock(side_effect=transport.ReportCLIError('quota')))
    out=tmp_path/'report.md';err=tmp_path/'error.txt'
    assert asyncio.run(research._run_claude('synthetic',out,err,asyncio.Semaphore(1)))==1
    assert not out.exists()
    assert 'quota' in err.read_text()


def test_async_cancellation_reaps_without_fallback(monkeypatch,tmp_path):
    import sys
    monkeypatch.setattr(transport,'LEDGER',tmp_path/'ledger.sqlite')
    monkeypatch.setattr(transport,'command',lambda *args:[sys.executable,'-c','import time;time.sleep(20)'])
    async def run():
        task=asyncio.create_task(transport.acomplete('synthetic'))
        await asyncio.sleep(.1)
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        else: raise AssertionError('cancellation swallowed')
    asyncio.run(run())
    import sqlite3
    with sqlite3.connect(transport.LEDGER) as conn:
        assert conn.execute('SELECT provider,status FROM attempts').fetchall()==[('claude','cancelled')]
