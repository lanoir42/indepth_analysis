from unittest.mock import Mock

import pytest

from indepth_analysis.kcif import topics


@pytest.fixture
def topic_update(monkeypatch):
    topic = {"slug": "synthetic", "title": "합성 토픽", "keywords": ["정책"],
             "summary_text": "(10/6) 최신 정책은 유지됐다."}
    candidates = [{"report_id": 17, "text_id": 901, "published_date": "2026-09-01",
                   "title": "과거 정책 전망", "text": "당시에는 정책 변경을 예상했다."}]
    monkeypatch.setattr(topics.store, "get_topic", Mock(return_value=topic))
    monkeypatch.setattr(topics.store, "scan_candidates", Mock(return_value=candidates))
    monkeypatch.setattr(topics.store, "timeline", Mock(return_value=[
        {"event_date": "2026-10-06", "headline": "최신 정책 유지"}]))
    monkeypatch.setattr(topics, "_kst_today", lambda: "2026-10-07")
    writes = {}
    for name in ("add_evidence", "add_events", "update_summary", "advance_watermark"):
        writes[name] = Mock(return_value=1)
        monkeypatch.setattr(topics.store, name, writes[name])
    result = {"relevant_report_ids": [17], "events": [
        {"event_date": "2026-09-01", "headline": "당시 정책 변경 전망", "report_ids": [17]}],
        "summary": "(9/1) 당시 변경 전망이 있었으나 (10/6) 최신 정책은 유지됐다."}
    call = Mock(return_value=result)
    monkeypatch.setattr(topics.llm, "call_json", call)
    return candidates, result, call, writes


def test_late_text_uses_original_date_and_preserves_recent_context(topic_update):
    candidates, result, call, writes = topic_update
    outcome = topics.update_topic("synthetic")
    assert outcome["ok"]
    prompt = call.call_args.args[0]
    assert "[늦게 확보된 과거 자료 처리]" in prompt
    assert "(10/6) 최신 정책은 유지됐다." in prompt
    assert "본문 확보일은 사건일이 아닙니다" in prompt
    assert "id=17 | 2026-09-01" in prompt
    assert writes["add_events"].call_args.args[1][0]["event_date"] == "2026-09-01"
    writes["advance_watermark"].assert_called_once_with("synthetic", 901)


@pytest.mark.parametrize("day, report_ids", [
    ("2026-10-07", [17]), ("2026-10-06", [17]), ("2026-09-01", [999]),
    ("2026-09-01", []),
])
def test_late_event_date_mismatch_keeps_all_state_untouched(topic_update, day, report_ids):
    candidates, result, call, writes = topic_update
    result["events"][0].update(event_date=day, report_ids=report_ids)
    outcome = topics.update_topic("synthetic")
    assert not outcome["ok"]
    assert outcome["reason"] == "late_event_date_mismatch"
    for write in writes.values():
        write.assert_not_called()


def test_normal_candidate_does_not_change_prompt_contract(topic_update):
    candidates, result, call, writes = topic_update
    candidates[0]["published_date"] = "2026-10-07"
    result["events"][0]["event_date"] = "2026-10-07"
    assert topics.update_topic("synthetic")["ok"]
    assert "늦게 확보된 과거 자료" not in call.call_args.args[0]
    assert "[기존 현재 상황]" not in call.call_args.args[0]


def test_irrelevant_late_candidate_can_advance_without_events(topic_update):
    candidates, result, call, writes = topic_update
    result.update(relevant_report_ids=[], events=[], summary="")
    assert topics.update_topic("synthetic")["ok"]
    writes["update_summary"].assert_not_called()
    writes["advance_watermark"].assert_called_once_with("synthetic", 901)


def test_mixed_old_and_new_sources_allow_one_cited_publication_date(topic_update):
    candidates, result, call, writes = topic_update
    candidates.append({"report_id": 18, "text_id": 902, "published_date": "2026-10-07",
                       "title": "최신 정책", "text": "최신 상황"})
    result["events"][0].update(event_date="2026-10-07", report_ids=[17, 18])
    assert topics.update_topic("synthetic")["ok"]
    writes["advance_watermark"].assert_called_once_with("synthetic", 902)


def test_late_candidate_llm_failure_preserves_state(topic_update):
    candidates, result, call, writes = topic_update
    call.return_value = None
    assert topics.update_topic("synthetic")["reason"] == "llm_failed"
    for write in writes.values():
        write.assert_not_called()


def test_late_duplicate_outside_recent_prompt_is_not_reinserted(topic_update):
    candidates, result, call, writes = topic_update
    topics.store.timeline.return_value = [
        {"event_date": "2026-09-01", "headline": "당시   정책 변경 전망"},
        *[{"event_date": "2026-10-06", "headline": f"최근 상황 {index}"}
          for index in range(20)],
    ]
    assert topics.update_topic("synthetic")["ok"]
    assert "2026-09-01 — 당시" not in call.call_args.args[0]
    writes["add_events"].assert_called_once_with("synthetic", [])
    writes["add_evidence"].assert_called_once_with("synthetic", [17])
    writes["advance_watermark"].assert_called_once_with("synthetic", 901)


def test_late_batch_internal_exact_duplicate_is_not_reinserted(topic_update):
    candidates, result, call, writes = topic_update
    result["events"].append(dict(result["events"][0], headline="당시  정책 변경 전망"))
    assert topics.update_topic("synthetic")["ok"]
    assert len(writes["add_events"].call_args.args[1]) == 1
