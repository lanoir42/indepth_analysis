"""W-b 섀도 훅 — `kcif.monthly`(`kcif/report.py:_render_period`의 도구 없는
월간 종합 서술 콜) opt-in caller가 분기 호출은 건드리지 않고 정확히 월간
호출에만 실리는지 (계약 REPORT-ROUTING.md §7, ReportSpec kcif_monthly.toml).

Real store/CLI에 닿지 않는다 — `llm.call_text`/`report_cli.complete`를 직접
가로챈다.
"""

from __future__ import annotations

from datetime import date

import pytest

from indepth_analysis.kcif import llm as kcif_llm
from indepth_analysis.kcif import report as R


@pytest.fixture
def fake_store_with_topic(monkeypatch):
    topic = {"slug": "fomc", "title": "FOMC·미국 통화정책"}
    monkeypatch.setattr(R.store, "list_topics", lambda status=None: [topic])
    monkeypatch.setattr(R.store, "timeline",
                        lambda slug: [{"event_date": "2026-09-05", "headline": "h", "id": 1}])

    class _FakeConn:
        def execute(self, *a, **k):
            class _Rows:
                def fetchall(self_inner):
                    return []
            return _Rows()
    monkeypatch.setattr(R.store, "get_conn", lambda: _FakeConn())
    return topic


def test_render_period_forwards_caller_to_call_text(monkeypatch, fake_store_with_topic):
    seen = {}

    def fake_call_text(prompt, *, system, model, timeout, caller=None):
        seen["caller"] = caller
        return "- **FOMC**: 종합"
    monkeypatch.setattr(R.llm, "call_text", fake_call_text)

    R._render_period("제목", "라벨", ["2026-09"], {}, caller="kcif.monthly")
    assert seen["caller"] == "kcif.monthly"

    R._render_period("제목", "라벨", ["2026-09"], {})   # default — unchanged behaviour
    assert seen["caller"] is None


def test_self_heal_periodics_tags_monthly_only(monkeypatch, tmp_path):
    """monthly render passes caller='kcif.monthly'; quarterly stays caller=None
    (unchanged) — mirrors the W-a1 opt-in precedent (kcif.update_topic)."""
    monkeypatch.setattr(R, "REPORTS_OUT_DIR", tmp_path)
    calls = []

    def fake_render(title, period_label, prefixes, dump_paths, *, caller=None):
        calls.append(caller)
        return f"# {title}\n"
    monkeypatch.setattr(R, "_render_period", fake_render)

    # A month that is also the last month of a quarter (Sept → Q3) so both the
    # monthly and quarterly self-heal branches fire in one call.
    today = date(2026, 10, 15)
    made = R._self_heal_periodics(today, {}, {})
    assert len(made) == 2
    assert calls == ["kcif.monthly", None]


def test_call_text_forwards_caller_to_complete(monkeypatch):
    monkeypatch.setenv("INDEPTH_REPORT_FALLBACK", "1")
    seen = {}

    def fake_complete(prompt, *, tier, timeout, caller=None):
        seen["caller"] = caller
        return "본문"
    monkeypatch.setattr("indepth_analysis.report_cli.complete", fake_complete)
    monkeypatch.setattr("indepth_analysis.report_cli.enabled", lambda: True)

    assert kcif_llm.call_text("p", system="s", caller="kcif.monthly") == "본문"
    assert seen["caller"] == "kcif.monthly"

    kcif_llm.call_text("p", system="s")
    assert seen["caller"] is None
