"""KCIF 일간 리포트 — 당일 하이라이트 우선 레이아웃 · 주말/휴일 쉼 (2026-09-23).

실 references.db·reports/kcif에 닿지 않는다. store 함수와 출력 경로를 tmp로 바꾼다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest

from indepth_analysis.kcif import report as R
from indepth_analysis.kcif import schedule
from indepth_analysis.kcif import topics as topics_mod


# ── 하이라이트 추출 (LLM 0) ────────────────────────────────────────────────

BRIEF = """KCIF
1
❑ [이슈] 최근 미 10년물 국채금리가 5%를 상회한 가운데
학계에서 편의수익률이 소멸했다는 주장이 제기
 9.3일 월러 연준 이사는 편의수익률이 소멸했다고 지적
◼ [이슈] 최근 미 10년물 국채금리가 5%를 상회한 가운데
학계에서 편의수익률이 소멸했다는 주장이 제기
◼ [배경] 공급물량 증가와 가격 민감 투자자 역할 확대
◼ [영향] 국채금리 하방 요인이 약화
2026. 9. 22
◼ [시사점] 재정 건전화 과제를 제기
◼ [기타] 다섯 번째 항목은 상한 밖
"""

FLASH = """# [9.22] 속보
1
■ 주요 뉴스:\x01 미국 트럼프, 이란 대통령과 대화 가능
   ○ 연준 주요 인사, 추가 금리인상 필요
■ 해외시각: 美中 정상회담, 진전 어려울 가능성
■ 국제금융시장: 미국 주가 상승[+1.5%]
"""

WEEKLY = """주간 국제금융 주요 이슈 및 전망
안남기 | 전문위원 (3705-6232)
 미중 정상회의가 9.24일 백악관에서 개최. 관세·무역 등이 논의
 제81차 유엔총회의 고위급 회기 일반토의가 9.22~28일 진행
 세 번째 문단은 대체 경로 상한(2) 밖
"""

TABLE = "국제 및 국내 금융시장\n지표\n'25.8월\n952 (2.4%)\n985 (3.5%)\n"


def test_bracket_leads_dedupe_by_label_and_cap():
    hs = R.lead_highlights(BRIEF)
    assert [h.split("]")[0] + "]" for h in hs] == ["[이슈]", "[배경]", "[영향]", "[시사점]"]
    # 이어지는 줄은 합치고, 하위 글머리()·날짜 줄에서 멈춘다
    assert hs[0].endswith("주장이 제기")
    assert "월러" not in hs[0]
    assert "2026" not in hs[2]


def test_colon_leads_strip_control_chars_and_sub_bullets():
    hs = R.lead_highlights(FLASH)
    assert hs == ["주요 뉴스: 미국 트럼프, 이란 대통령과 대화 가능",
                  "해외시각: 美中 정상회담, 진전 어려울 가능성",
                  "국제금융시장: 미국 주가 상승[+1.5%]"]


def test_fallback_bullets_take_first_two():
    hs = R.lead_highlights(WEEKLY)
    assert len(hs) == 2 and hs[0].startswith("미중 정상회의")


def test_no_lead_paragraph_means_nothing_invented():
    assert R.lead_highlights(TABLE) == []
    assert R.lead_highlights(None) == []


def test_clip_prefers_sentence_boundary():
    text = "가" * 120 + ". " + "나" * 200
    out = R._clip(text, 200)
    assert out.endswith(".") and "나" not in out


# ── 하이라이트 창 (쉰 날 포함) ─────────────────────────────────────────────

@pytest.fixture
def out_dirs(tmp_path, monkeypatch):
    reports = tmp_path / "reports" / "kcif"
    markers = reports / ".skipped"
    monkeypatch.setattr(R, "REPORTS_OUT_DIR", reports)
    monkeypatch.setattr(R, "SKIP_MARKER_DIR", markers)
    monkeypatch.setattr(R, "LOCK_PATH", tmp_path / "kcif_daily.lock")
    return reports, markers


def test_window_monday_covers_weekend(out_dirs):
    assert R.highlight_window_start(date(2026, 9, 21)) == date(2026, 9, 19)   # 월 → 토
    assert R.highlight_window_start(date(2026, 9, 22)) == date(2026, 9, 22)   # 화


def test_window_covers_marked_holiday(out_dirs):
    _, markers = out_dirs
    markers.mkdir(parents=True)
    (markers / "2026-09-23.json").write_text("{}", encoding="utf-8")
    assert R.highlight_window_start(date(2026, 9, 24)) == date(2026, 9, 23)


# ── 렌더 순서 ─────────────────────────────────────────────────────────────

@pytest.fixture
def fake_store(monkeypatch):
    topic = {"slug": "fomc", "title": "FOMC·미국 통화정책", "summary_text": "현재 상황 본문"}
    monkeypatch.setattr(R.store, "list_topics", lambda status=None: [topic])
    monkeypatch.setattr(R.store, "evidence_stats",
                        lambda slug: {"total": 3, "categories": [("채권", 3)]})
    monkeypatch.setattr(R.store, "timeline", lambda slug: [])
    return topic


def _new(**kw):
    base = {"id": 1, "title": "미 국채 편의수익률", "category": "채권",
            "md_path": "references/KCIF_md/x.md", "extracted": True,
            "highlights": ["[이슈] 편의수익률 소멸"], "topics": [("FOMC·미국 통화정책", 1)]}
    base.update(kw)
    return base


def test_render_order_highlight_first(fake_store):
    md = R.render_daily("2026-09-22", {"crawl": "성공"}, {}, [_new()])
    heads = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert heads == ["## 오늘의 KCIF (1건)", "## Executive summary", "## 실행 상태",
                     "## 별첨: 토픽별 타임라인"]
    assert "[별첨](#별첨-토픽별-타임라인)" in md
    lines = md.splitlines()
    i = lines.index("### [채권] 미 국채 편의수익률")
    assert lines[i + 2] == "- [이슈] 편의수익률 소멸"
    assert lines[i + 3] == "- 토픽 반영: FOMC·미국 통화정책 1건"
    # md 경로는 자기 줄에 절대경로로 (nvim gf · orchestrator 스크럽)
    assert lines[i + 4] == str(R.PROJECT_ROOT / "references/KCIF_md/x.md")


def test_render_zero_reports_one_line(fake_store):
    md = R.render_daily("2026-09-22", {}, {}, [])
    assert "## 오늘의 KCIF (0건)\n\n- 오늘 신규 리포트 없음\n" in md


def test_render_not_extracted(fake_store):
    md = R.render_daily("2026-09-22", {}, {}, [_new(md_path=None, extracted=False,
                                                     highlights=[], topics=[])])
    assert "- (본문 추출 전)" in md
    assert "KCIF_md" not in md


def test_render_legacy_rows_without_highlight_keys(fake_store):
    """폴백 경로(제목 목록만) — 키가 없어도 깨지지 않는다."""
    md = R.render_daily("2026-09-22", {}, {}, [{"title": "제목", "category": "미국",
                                                 "md_path": None}])
    assert "### [미국] 제목" in md and "본문 추출 전" not in md


# ── 주말/휴일 쉼 ───────────────────────────────────────────────────────────

@pytest.fixture
def pipeline(monkeypatch, out_dirs, fake_store):
    calls = {"crawl": 0, "topics": 0}
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE reports (id INTEGER, published_date TEXT)")
    monkeypatch.setattr(R.store, "get_conn", lambda: conn)

    def crawl(status, target, *, new=0):
        calls["crawl"] += 1
        status["crawl"] = f"성공 · 신규 카탈로그 {new}건"
        status["_new_count"] = new

    def update_all():
        calls["topics"] += 1
        return []

    monkeypatch.setattr(R, "_crawl_and_ingest", crawl)
    monkeypatch.setattr(topics_mod, "update_all", update_all)
    monkeypatch.setattr(topics_mod, "write_topic_dumps", lambda active: {})
    monkeypatch.setattr(R, "collect_new_reports", lambda day: ([], ""))
    monkeypatch.setattr(R, "_self_heal_periodics", lambda *a, **k: [])
    return {"calls": calls, "conn": conn, "dirs": out_dirs}


def test_weekend_does_nothing(pipeline):
    reports, markers = pipeline["dirs"]
    res = R.run_daily("2026-09-19")          # 토
    assert res["skipped"] == "weekend"
    assert pipeline["calls"] == {"crawl": 0, "topics": 0}
    assert not (reports / "2026-09-19-kcif-topics.md").exists()
    assert json.loads((markers / "2026-09-19.json").read_text())["reason"] == "weekend"


def test_weekend_force_runs(pipeline):
    reports, _ = pipeline["dirs"]
    res = R.run_daily("2026-09-20", force=True)
    assert "skipped" not in res
    assert (reports / "2026-09-20-kcif-topics.md").exists()


def test_holiday_skip_when_crawl_ok_and_zero_new(pipeline):
    reports, markers = pipeline["dirs"]
    res = R.run_daily("2026-09-24")          # 목
    assert res["skipped"] == "no_new_reports"
    assert pipeline["calls"]["topics"] == 0
    assert not (reports / "2026-09-24-kcif-topics.md").exists()
    assert json.loads((markers / "2026-09-24.json").read_text())["reason"] == "no_new_reports"


def test_zero_new_catalog_but_reports_dated_today_still_writes(pipeline):
    pipeline["conn"].execute("INSERT INTO reports VALUES (1, '2026-09-24')")
    reports, _ = pipeline["dirs"]
    R.run_daily("2026-09-24")
    assert (reports / "2026-09-24-kcif-topics.md").exists()


def test_crawl_failure_still_writes_report(pipeline, monkeypatch):
    def boom(status, target):
        raise RuntimeError("network down")
    monkeypatch.setattr(R, "_crawl_and_ingest", boom)
    reports, markers = pipeline["dirs"]
    res = R.run_daily("2026-09-24")
    assert "skipped" not in res
    md = (reports / "2026-09-24-kcif-topics.md").read_text(encoding="utf-8")
    assert "크롤: 실패 — network down" in md
    assert not (markers / "2026-09-24.json").exists()


def test_skip_crawl_never_holiday_skips(pipeline):
    reports, _ = pipeline["dirs"]
    R.run_daily("2026-09-24", skip_crawl=True)
    assert (reports / "2026-09-24-kcif-topics.md").exists()


def test_report_write_clears_stale_marker(pipeline):
    reports, markers = pipeline["dirs"]
    R.run_daily("2026-09-24")                              # 휴일 판정 → 표지
    assert (markers / "2026-09-24.json").exists()
    R.run_daily("2026-09-24", force=True)                  # 강제 실행 → 리포트
    assert (reports / "2026-09-24-kcif-topics.md").exists()
    assert not (markers / "2026-09-24.json").exists()


# ── launchd 스케줄 ─────────────────────────────────────────────────────────

def test_plist_is_weekdays_only():
    sci = schedule._build_plist()["StartCalendarInterval"]
    assert [d["Weekday"] for d in sci] == [1, 2, 3, 4, 5]
    assert all(d["Hour"] == 18 and d["Minute"] == 0 for d in sci)
