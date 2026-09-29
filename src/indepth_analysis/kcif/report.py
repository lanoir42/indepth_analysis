"""KCIF 일간/월간/분기 리포트 파이프라인 (18:00 KST launchd 잡의 본체).

무인 운영 원칙 (설계 패널):
- 각 단계(크롤/다운로드/추출/토픽/LLM) 개별 격리 — 어떤 실패에도 일간 리포트
  파일은 **무조건** 생성되고, ``## 실행 상태`` 섹션이 결정적으로 렌더되어
  orchestrator 저널이 곧 장애 알림 채널이 된다.
- 월간/분기는 별도 스케줄이 아니라 매 실행의 자가치유 체크(전월/전분기 파일
  부재 시 생성) — launchd misfire·전원 off에 강건.
- 인터랙티브 절대 금지 (nvim 등) — cron-safe.
- 2026-09-23: 일간 리포트는 **당일 발행분 하이라이트가 맨 앞**이고(신규 효과)
  토픽 '현재 상황'이 그 다음이다(어제 본 내용의 반복 학습). 토·일은 KCIF도
  쉬므로 리포트를 만들지 않고, 평일이라도 크롤이 성공했는데 신규 카탈로그와
  당일 발행분이 모두 0건이면 휴일로 보고 쉰다. 쉰 날은 `.skipped/{date}.json`
  표지를 남긴다(`--force`로 강제 실행). 크롤이 실패한 날은 쉬지 않는다 —
  "어떤 실패에도 일간 리포트는 생성된다"는 보장은 그대로다.
"""

from __future__ import annotations

import fcntl
import json
import logging
import random
import re
import time
from datetime import date as date_cls
from datetime import datetime, timedelta

from indepth_analysis.kcif import llm, store, topics as topics_mod
from indepth_analysis.kcif.paths import (
    KST, LOCK_PATH, PDF_DIR, PROJECT_ROOT, REPORTS_OUT_DIR, SKIP_MARKER_DIR,
)

logger = logging.getLogger(__name__)

DOWNLOAD_CAP_PER_RUN = 50
DOWNLOAD_RECENT_DAYS = 14   # PENDING 재시도 대상 published_date 윈도우
FAILED_RETRY_DAYS = 7       # FAILED → PENDING 리셋 윈도우
SLEEP_BASE_S = 0.7

MONTHLY_SYNTH_SYSTEM = (
    "당신은 국제금융 리서치 요약 분석가입니다. 한 달(또는 분기)간의 토픽별 "
    "타임라인을 바탕으로 거시경제·정치 관점의 변화를 한국어로 종합 서술합니다. "
    "객관적·건조하게, 토픽별 3~5문장. 제공된 이벤트에 없는 사실 금지. "
    "마크다운은 - 불릿과 **굵게**만 사용."
)


def _today_kst() -> date_cls:
    return datetime.now(KST).date()


# ── 크롤/다운로드/추출 ─────────────────────────────────────────────────────

def _crawl_and_ingest(status: dict, target: date_cls) -> None:
    """당월(월초 3일간은 전월도) 카탈로그 크롤 → 신규 다운로드 → .md 추출."""
    from indepth_analysis.data.kcif_client import KCIFScraper
    from indepth_analysis.db import ReferenceDB
    from indepth_analysis.models.reference import DownloadStatus, Report

    db = ReferenceDB(db_path=PROJECT_ROOT / "references" / "references.db")
    scraper = KCIFScraper()
    source = db.get_or_create_source(scraper.source_name, scraper.base_url)

    months = [(target.year, target.month)]
    if target.day <= 3:
        prev = (target.replace(day=1) - timedelta(days=1))
        months.append((prev.year, prev.month))

    file_urls: dict[str, str] = {}
    new_count = 0
    for y, m in months:
        results = scraper.scrape_listing(year=y, month=m)
        for r in results:
            if r.file_url:
                file_urls[r.external_id] = r.file_url
            report = Report(
                source_id=source.id, external_id=r.external_id, title=r.title,
                category=r.category or "", author=r.author or "",
                published_date=r.published_date, url=r.url,
            )
            existing = db.conn.execute(
                "SELECT id FROM reports WHERE source_id = ? AND external_id = ?",
                (source.id, r.external_id)).fetchone()
            report = db.upsert_report(report)
            if not existing:
                new_count += 1
            if r.file_url:
                db.conn.execute(
                    "UPDATE reports SET file_url = COALESCE(file_url, ?) WHERE id = ?",
                    (r.file_url, report.id))
        db.conn.commit()
        time.sleep(SLEEP_BASE_S + random.random() * 0.5)
    db.update_source_scraped(source.id)
    status["crawl"] = f"성공 · 신규 카탈로그 {new_count}건"
    status["_new_count"] = new_count

    # FAILED 자가치유: 최근 N일 발행분만 PENDING으로 1회 리셋
    cutoff = (target - timedelta(days=FAILED_RETRY_DAYS)).isoformat()
    cur = db.conn.execute(
        "UPDATE reports SET download_status = 'pending', download_error = NULL "
        "WHERE source_id = ? AND download_status = 'failed' "
        "AND COALESCE(published_date,'') >= ?", (source.id, cutoff))
    db.conn.commit()
    if cur.rowcount:
        logger.info("kcif: FAILED %d건 → PENDING 리셋", cur.rowcount)

    # 다운로드: 최근 N일 PENDING만, 실행당 상한 — 과거 백로그 폭주 방지
    dl_cutoff = (target - timedelta(days=DOWNLOAD_RECENT_DAYS)).isoformat()
    rows = db.conn.execute(
        "SELECT id FROM reports WHERE source_id = ? AND download_status = 'pending' "
        "AND COALESCE(published_date,'') >= ? ORDER BY published_date DESC LIMIT ?",
        (source.id, dl_cutoff, DOWNLOAD_CAP_PER_RUN)).fetchall()
    downloaded = 0
    from indepth_analysis.data.scraper_base import ScraperResult
    for row in rows:
        report = db.get_report_by_id(row["id"])
        if not report:
            continue
        fu_row = db.conn.execute(
            "SELECT file_url FROM reports WHERE id = ?", (report.id,)).fetchone()
        sr = ScraperResult(
            external_id=report.external_id, title=report.title,
            category=report.category, author=report.author,
            published_date=report.published_date, url=report.url,
            file_url=file_urls.get(report.external_id)
            or (fu_row["file_url"] if fu_row else None),
        )
        try:
            path = scraper.download_file(sr, PDF_DIR)
            if path:
                from indepth_analysis.data.kcif_client import file_hash
                db.update_report_download(
                    report.id, status=DownloadStatus.DOWNLOADED,
                    file_name=path.name, file_size_bytes=path.stat().st_size,
                    file_hash=file_hash(path))
                downloaded += 1
            else:
                db.update_report_download(report.id, status=DownloadStatus.RESTRICTED,
                                          error="no file url / restricted")
        except Exception as e:
            db.update_report_download(report.id, status=DownloadStatus.FAILED,
                                      error=str(e)[:300])
        time.sleep(SLEEP_BASE_S + random.random() * 0.5)
    status["download"] = f"성공 · {downloaded}건 다운로드"

    # .md 추출 (md 미생성 + 다운로드 완료 전체 — 신규분과 밀린 분 함께)
    from indepth_analysis.kcif.extract_md import backfill_all
    res = backfill_all(db, source.id)
    status["extract"] = f"성공 · {res['ok']}건 추출" + (f", 실패 {res['fail']}건" if res["fail"] else "")
    db.close()



# ── 당일 하이라이트 (LLM 0회) ────────────────────────────────────────────────
#
# KCIF 본문 첫 장에는 발행처가 직접 쓴 요약 문단이 있다. 실측(2026-08~09 발행분
# 본문 108건): 국제금융속보는 `■ 주요 뉴스: …`·`■ 해외시각: …`·`■ 국제금융시장:
# …`, 분석 리포트는 `◼/❑ [이슈] …`·`[배경]`·`[영향]`·`[시사점]`이고, 일부 PDF는
# 같은 글머리가 사용자 영역 글리프(U+F06E·U+F06F·U+F0A8 등)로 추출된다. 이 문단을
# 그대로 옮긴다 — 모델에게 요약시키지 않는다(없는 말을 만들지 않게).

HIGHLIGHT_MAX_ITEMS = 4
HIGHLIGHT_MAX_CHARS = 200
HIGHLIGHT_REPORT_CAP = 30

# 요약 문단 글머리 글리프 — 사각형 계열 + PDF 추출 시 깨진 사용자 영역 글리프.
_LEAD_GLYPHS = "◼■❑□▪"
_LEAD_BRACKET_RE = re.compile(
    rf"^\s*[{_LEAD_GLYPHS}-]\s*(\[[^\]\n]{{1,8}}\])\s*(\S.*)$")
# 속보형 `■ 주요 뉴스: …` — ■ 글리프에만 허용(콜론 앞 라벨 10자 이하).
_LEAD_COLON_RE = re.compile(r"^\s*[■◼]\s*([^:：\[\]\n]{1,10})[:：]\s*(\S.*)$")
# 요약 문단이 없는 문서(주간·은행 일부)의 대체 — 1단 글머리 문단 앞 2개.
_LEAD_BULLET_RE = re.compile(r"^\s*[-①②③④⑤⑥⑦⑧⑨]\s*(\S.*)$")
# 이어지는 줄이 아니라 새 항목/잡음의 시작으로 보는 줄머리.
_STOP_RE = re.compile(
    rf"^\s*($|[{_LEAD_GLYPHS}-①②③④⑤⑥⑦⑧⑨○•·*※<\-–—－]|\d{{4}}\s*\.\s*\d)")


# PDF 추출이 남기는 제어문자(실측 속보 `\x01`)·폭 없는 글자 — 화면에 안 보이지만
# 공백 정규화를 어긋나게 한다.
_INVISIBLE_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200d\u2060\ufeff]")


def _clip(text: str, limit: int = HIGHLIGHT_MAX_CHARS) -> str:
    """문장 경계 우선 절단. 경계가 없으면 낱말 경계에서 자르고 `…`."""
    text = re.sub(r"\s+", " ", _INVISIBLE_RE.sub("", text)).strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for mark in (". ", "다. ", "。"):
        i = head.rfind(mark)
        if i >= limit * 0.5:
            return head[: i + len(mark)].rstrip()
    i = max(head.rfind(", "), head.rfind(" "))
    if i >= limit * 0.5:
        head = head[:i]
    return head.rstrip(" ,") + "…"


def _join_continuation(lines: list[str], i: int, first: str) -> str:
    parts = [first.strip()]
    j = i + 1
    while j < len(lines) and not _STOP_RE.match(lines[j]) and len(" ".join(parts)) < 400:
        seg = lines[j].strip()
        if "|" in seg or seg in ("KCIF", "Brief", "Market Brief", "Issue Analysis"):
            break
        parts.append(seg)
        j += 1
    return " ".join(parts)


def lead_highlights(text: str | None, *, max_items: int = HIGHLIGHT_MAX_ITEMS) -> list[str]:
    """본문에서 발행처 자신의 요약 문단을 뽑는다. 못 찾으면 빈 목록(지어내지 않는다)."""
    if not text:
        return []
    lines = text.splitlines()
    out: list[str] = []
    seen_labels: set[str] = set()
    seen_text: set[str] = set()

    def _add(label: str, body: str) -> None:
        label = re.sub(r"\s+", " ", _INVISIBLE_RE.sub("", label)).strip()
        key = label.strip("[] ").replace(" ", "")
        if key in seen_labels:
            return
        clipped = _clip(f"{label} {body}" if label.startswith("[") else f"{label}: {body}")
        norm = re.sub(r"\s+", "", clipped)
        if norm in seen_text:
            return
        seen_labels.add(key)
        seen_text.add(norm)
        out.append(clipped)

    for i, ln in enumerate(lines):
        if len(out) >= max_items:
            break
        m = _LEAD_BRACKET_RE.match(ln) or _LEAD_COLON_RE.match(ln)
        if m:
            _add(m.group(1).strip(), _join_continuation(lines, i, m.group(2)))
    if out:
        return out

    # 요약 문단이 없는 문서 — 1단 글머리 문단 앞 2개만.
    for i, ln in enumerate(lines):
        if len(out) >= 2:
            break
        m = _LEAD_BULLET_RE.match(ln)
        if m:
            body = _clip(_join_continuation(lines, i, m.group(1)))
            if len(body) >= 15 and re.sub(r"\s+", "", body) not in seen_text:
                seen_text.add(re.sub(r"\s+", "", body))
                out.append(body)
    return out


def _is_skip_day(d: date_cls) -> bool:
    """주말이거나 휴일 표지가 남은 날 — 하이라이트 창을 뒤로 넓힐 때 건너뛴다."""
    return d.weekday() >= 5 or (SKIP_MARKER_DIR / f"{d.isoformat()}.json").exists()


def highlight_window_start(day: date_cls, *, max_back: int = 7) -> date_cls:
    """하이라이트 창의 첫날. 직전 리포트 작성일 다음 날부터 오늘까지다.

    KCIF는 토요일에도 국제금융속보를 낸다(실측 2026년 64건). 주말에 리포트를
    쉬면 그 발행분이 어디에도 안 뜨므로 월요일(또는 휴일 다음 날) 창이 쉬었던
    날을 함께 덮는다. 창을 여는 쪽은 결정론 — 요일과 `.skipped/` 표지만 본다.
    """
    start = day
    for _ in range(max_back):
        prev = start - timedelta(days=1)
        if not _is_skip_day(prev):
            break
        start = prev
    return start


def collect_new_reports(day: date_cls) -> tuple[list[dict], str]:
    """하이라이트 대상 — 창 안 발행분 + 본문 요약 문단 + 반영된 토픽. 읽기 전용."""
    start = highlight_window_start(day)
    conn = store.get_conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT r.id, r.title, r.category, r.md_path, r.published_date, t.text "
        "FROM reports r LEFT JOIN report_texts t ON t.report_id = r.id "
        "WHERE COALESCE(r.published_date,'') >= ? AND COALESCE(r.published_date,'') <= ? "
        "ORDER BY r.published_date ASC, r.id ASC",
        (start.isoformat(), day.isoformat())).fetchall()]
    fed: dict[int, list[tuple[str, int]]] = {}
    ids = [r["id"] for r in rows]
    if ids:
        marks = ",".join("?" for _ in ids)
        for fr in conn.execute(
            "SELECT CAST(j.value AS INTEGER) AS rid, tp.title AS title, COUNT(*) AS n "
            "FROM kcif_topic_events e JOIN kcif_topics tp ON tp.id = e.topic_id, "
            "     json_each(e.report_ids_json) j "
            f"WHERE CAST(j.value AS INTEGER) IN ({marks}) "
            "GROUP BY rid, tp.id ORDER BY rid, n DESC, tp.title", ids).fetchall():
            fed.setdefault(int(fr["rid"]), []).append((fr["title"], int(fr["n"])))
    for r in rows:
        text = r.pop("text", None)
        r["extracted"] = bool(text)
        r["highlights"] = lead_highlights(text)
        r["topics"] = fed.get(r["id"], [])
    label = "" if start == day else f"{start.isoformat()} ~ {day.isoformat()}"
    return rows, label


def _render_highlights(new_reports: list[dict], window_label: str = "") -> list[str]:
    lines = [f"## 오늘의 KCIF ({len(new_reports)}건)", ""]
    if window_label:
        lines += [f"주말·휴일에 쉰 날의 발행분을 함께 싣습니다 ({window_label}).", ""]
    if not new_reports:
        return lines + ["- 오늘 신규 리포트 없음", ""]
    for r in new_reports[:HIGHLIGHT_REPORT_CAP]:
        lines.append(f"### [{r.get('category') or '?'}] {r['title']}")
        lines.append("")
        highlights = r.get("highlights")
        if highlights is None:            # 구 호출부(하이라이트 미수집) — 제목만
            highlights = []
        if r.get("extracted") is False:
            lines.append("- (본문 추출 전)")
        for h in highlights:
            lines.append(f"- {h}")
        topics = r.get("topics") or []
        if topics:
            lines.append("- 토픽 반영: " + " · ".join(f"{t} {n}건" for t, n in topics))
        if r.get("md_path"):
            lines.append(str(PROJECT_ROOT / r["md_path"]))
        lines.append("")
    if len(new_reports) > HIGHLIGHT_REPORT_CAP:
        lines += [f"- (외 {len(new_reports) - HIGHLIGHT_REPORT_CAP}건 — `indepth kcif find`로 조회)", ""]
    return lines

# ── 렌더 ───────────────────────────────────────────────────────────────────

def _date_minus(date_str: str, days: int) -> str:
    return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


def render_daily(date_str: str, status: dict, dump_paths: dict[str, str],
                 new_reports: list[dict], window_label: str = "") -> str:
    """Daily topic report.

    2026-08-26 재구성 (사용자 요청): the Executive summary IS the report. It
    used to be a list of one-sentence-per-topic lines above a wall of
    timelines; reading it meant reading the same ground twice, once compressed
    beyond usefulness and once at full length. Now each topic's **현재 상황**
    — which already reads as a paragraph and now carries inline dates (see
    topics.TOPIC_UPDATE_SYSTEM rule 7) — is the main content, and the raw
    timelines move to an appendix for when someone wants to audit a claim.

    2026-09-23 (사용자 요청): 당일 발행분 하이라이트(`## 오늘의 KCIF`)가 맨
    앞, 토픽 '현재 상황'이 그 다음이다 — 신규 효과 뒤에 어제 본 내용을 반복해
    읽는다. `## Executive summary` 제목 문구는 그대로 둔다: orchestrator
    3줄 요약(`summary3.PREFERRED_WINDOW["kcif"]`)이 그 제목으로 창을 잡는다.
    별첨 앵커(`#별첨-토픽별-타임라인`)도 불변이다.
    """
    active = store.list_topics(status="active")
    lines = [
        f"# KCIF 토픽 브리프 — {date_str}",
        "",
        f"활성 토픽 {len(active)}개 — KCIF(국제금융센터) 리포트 기반 자동 추적. "
        f"맨 앞은 오늘 발행된 KCIF 리포트의 하이라이트이고, 이어지는 각 토픽의 "
        f"'현재 상황'이 누적 흐름입니다. 근거 타임라인은 문서 끝 별첨에 있습니다.",
        "",
    ]
    lines += _render_highlights(new_reports, window_label)
    lines += [
        "## Executive summary",
        "",
    ]
    for t in active:
        summary = (t.get("summary_text") or "").strip()
        lines.append(f"### {t['title']}")
        lines.append("")
        lines.append(summary or "_(요약 대기 — 아직 수집된 근거가 없습니다)_")
        lines.append("")
        ev = store.evidence_stats(t["slug"])
        cats = ", ".join(f"{c} {n}건" for c, n in ev["categories"]) or "(없음)"
        lines.append(f"<sub>근거 {ev['total']}건 — {cats} · "
                     f"타임라인은 [별첨](#별첨-토픽별-타임라인)</sub>")
        lines.append("")

    lines.append("## 실행 상태")
    lines.append("")
    for key, label in (("crawl", "크롤"), ("download", "다운로드"),
                       ("extract", "텍스트 추출"), ("topics", "토픽 업데이트")):
        lines.append(f"- {label}: {status.get(key, '실행 안 됨')}")
    lines.append("")

    # ── 별첨 ────────────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## 별첨: 토픽별 타임라인")
    lines.append("")
    lines.append("각 토픽의 최근 14일 이벤트입니다. 본문 '현재 상황'의 근거를 "
                 "날짜별로 확인할 때 봅니다.")
    lines.append("")
    cutoff = _date_minus(date_str, 13)  # 최근 14일 윈도우
    for t in active:
        slug = t["slug"]
        lines.append(f"### {t['title']} ({slug})")
        lines.append("")
        events = store.timeline(slug)
        recent = [e for e in events if str(e.get("event_date") or "") >= cutoff]
        older = len(events) - len(recent)
        if len(recent) > 20:
            older += len(recent) - 20
            recent = recent[-20:]
        if recent:
            for e in recent:
                lines.append(f"- {e['event_date']} — {e['headline']}")
        else:
            lines.append("- 최근 14일 신규 이벤트 없음")
        if older:
            lines.append(f"- (이전 이벤트 {older}건 — 원문 파일 참조)")
        dump = dump_paths.get(slug)
        if dump:
            lines.append("- **원문 조회**:")
            lines.append(dump)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _month_events(topic_slug: str, ym: str) -> list[dict]:
    return [e for e in store.timeline(topic_slug)
            if str(e.get("event_date") or "").startswith(ym)]


def _render_period(title: str, period_label: str, prefixes: list[str],
                   dump_paths: dict[str, str], *, caller: str | None = None) -> str:
    """월간/분기 공용 렌더 — prefixes: event_date가 시작해야 하는 YYYY-MM 목록.

    ``caller`` — W-b 섀도 훅(opt-in, 월간 호출부만 ``kcif.monthly``를 넘긴다).
    분기 호출은 그대로 ``None``이라 동작이 한 글자도 바뀌지 않는다.
    """
    active = store.list_topics(status="active")
    conn = store.get_conn()
    likes = " OR ".join("COALESCE(published_date,'') LIKE ?" for _ in prefixes)
    cat_rows = conn.execute(
        f"SELECT COALESCE(NULLIF(category,''),'기타') AS cat, COUNT(*) AS n "
        f"FROM reports WHERE ({likes}) GROUP BY cat ORDER BY n DESC LIMIT 10",
        [f"{p}%" for p in prefixes]).fetchall()

    lines = [f"# {title}", "",
             f"{period_label} KCIF 리포트 기반 토픽 타임라인 종합입니다.", "",
             "## 수집 통계", ""]
    total = sum(r["n"] for r in cat_rows)
    lines.append(f"- 기간 내 카탈로그 {total}건 — " +
                 (", ".join(f"{r['cat']} {r['n']}건" for r in cat_rows) or "(없음)"))
    lines.append("")

    # LLM 종합 서술 (sonnet 1콜, 실패 시 섹션 생략 — 타임라인은 항상 렌더)
    synth_input = []
    for t in active:
        evs = [e for p in prefixes for e in _month_events(t["slug"], p)]
        if not evs:
            continue
        synth_input.append(f"[{t['title']}]\n" + "\n".join(
            f"- {e['event_date']} — {e['headline']}" for e in evs))
    synth = None
    if synth_input:
        synth = llm.call_text(
            f"{period_label} 토픽별 타임라인:\n\n" + "\n\n".join(synth_input) +
            "\n\n토픽별로 '- **토픽명**: 종합 서술' 형식으로.",
            system=MONTHLY_SYNTH_SYSTEM, model="sonnet", timeout=300, caller=caller)
    if synth:
        lines.append("## 기간 종합")
        lines.append("")
        lines.append(synth)
        lines.append("")

    for t in active:
        evs = [e for p in prefixes for e in _month_events(t["slug"], p)]
        lines.append(f"## {t['title']} ({t['slug']})")
        lines.append("")
        if evs:
            for e in sorted(evs, key=lambda x: (x["event_date"], x["id"])):
                lines.append(f"- {e['event_date']} — {e['headline']}")
        else:
            lines.append("- 기간 내 이벤트 없음")
        dump = dump_paths.get(t["slug"])
        if dump:
            lines.append("- **원문 조회**:")
            lines.append(dump)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _self_heal_periodics(today: date_cls, dump_paths: dict[str, str], status: dict) -> list[str]:
    """전월/전분기 리포트 부재 시 생성 (idempotent). 반환: 생성 파일 경로."""
    made = []
    REPORTS_OUT_DIR.mkdir(parents=True, exist_ok=True)
    prev_month_end = today.replace(day=1) - timedelta(days=1)
    ym = prev_month_end.strftime("%Y-%m")
    monthly = REPORTS_OUT_DIR / f"{ym}-kcif-monthly.md"
    if not monthly.exists():
        body = _render_period(f"KCIF 월간 타임라인 — {ym}", f"{ym} 한 달간", [ym], dump_paths,
                              caller="kcif.monthly")
        monthly.write_text(body, encoding="utf-8")
        made.append(str(monthly))

    q = (prev_month_end.month - 1) // 3 + 1
    q_months = [f"{prev_month_end.year}-{m:02d}" for m in range(3 * q - 2, 3 * q + 1)]
    # 분기 리포트는 그 분기가 '끝난 뒤'에만 (전월이 분기 마지막 달일 때)
    if prev_month_end.month % 3 == 0:
        qfile = REPORTS_OUT_DIR / f"{prev_month_end.year}-Q{q}-kcif-quarterly.md"
        if not qfile.exists():
            body = _render_period(f"KCIF 분기 타임라인 — {prev_month_end.year} Q{q}",
                                  f"{prev_month_end.year} {q}분기", q_months, dump_paths)
            qfile.write_text(body, encoding="utf-8")
            made.append(str(qfile))
    if made:
        status["periodic"] = f"월간/분기 생성: {len(made)}건"
    return made


# ── daily 진입점 ───────────────────────────────────────────────────────────

def write_skip_marker(date_s: str, reason: str, detail: str = "") -> str:
    """쉰 날 표지 `reports/kcif/.skipped/{date}.json` — 저널 스캔 밖(`.` 접두)."""
    SKIP_MARKER_DIR.mkdir(parents=True, exist_ok=True)
    marker = SKIP_MARKER_DIR / f"{date_s}.json"
    marker.write_text(json.dumps({
        "date": date_s, "reason": reason, "detail": detail,
        "written_at": datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(marker)


def run_daily(date_str: str | None = None, *, skip_crawl: bool = False,
              force: bool = False) -> dict:
    """18:00 KST 잡 본체. 어떤 단계가 실패해도 일간 리포트는 생성된다.

    쉬는 날(2026-09-23): 토·일은 아무것도 하지 않는다(크롤·LLM·파일 0). 평일이라도
    크롤이 **성공**했고 신규 카탈로그 0건 + 당일 발행분 0건이면 KCIF 휴일로 보고
    토픽 업데이트·리포트를 건너뛴다. 크롤 실패·`--skip-crawl`은 판단 근거가 없어
    종전대로 리포트를 만든다. `force=True`면 두 판정 모두 무시한다. 쉰 날의
    토픽 업데이트와 월간/분기 자가치유는 다음 실행이 워터마크·부재 판정으로
    그대로 따라잡는다(둘 다 idempotent).
    """
    today = _today_kst() if not date_str else datetime.strptime(date_str, "%Y-%m-%d").date()
    date_s = today.isoformat()

    if not force and today.weekday() >= 5:
        marker = write_skip_marker(date_s, "weekend")
        logger.info("kcif daily: %s 주말 — 실행 안 함 (--force로 강제)", date_s)
        return {"date": date_s, "skipped": "weekend", "marker": marker}

    # 동시 실행 가드 (launchd vs 수동)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.warning("kcif daily already running — skip")
        return {"date": date_s, "skipped": "already_running"}

    status: dict = {}
    try:
        crawl_ok = False
        if skip_crawl:
            status["crawl"] = status["download"] = status["extract"] = "스킵 (--skip-crawl)"
        else:
            try:
                _crawl_and_ingest(status, today)
                crawl_ok = True
            except Exception as e:
                logger.exception("kcif crawl stage failed")
                status.setdefault("crawl", f"실패 — {str(e)[:120]}")
                status.setdefault("download", "크롤 실패로 미실행")
                status.setdefault("extract", "크롤 실패로 미실행")

        if not force and crawl_ok and status.get("_new_count") == 0:
            n_today = store.get_conn().execute(
                "SELECT COUNT(*) FROM reports WHERE published_date = ?", (date_s,)
            ).fetchone()[0]
            if n_today == 0:
                marker = write_skip_marker(
                    date_s, "no_new_reports", "크롤 성공 · 신규 카탈로그 0건 · 당일 발행 0건")
                logger.info("kcif daily: %s 신규 0건(휴일 추정) — 리포트 생략", date_s)
                return {"date": date_s, "skipped": "no_new_reports",
                        "marker": marker, "status": status}

        try:
            results = topics_mod.update_all()
            ok = sum(1 for r in results if r["ok"])
            ev = sum(r["events_added"] for r in results)
            fallback = sum(1 for r in results if r["reason"] == "llm_failed")
            status["topics"] = (f"성공 {ok}/{len(results)} · 신규 이벤트 {ev}건"
                                + (f" · LLM 실패 {fallback}건(다음 실행 재시도)" if fallback else ""))
        except Exception as e:
            logger.exception("kcif topics stage failed")
            status["topics"] = f"실패 — {str(e)[:120]}"

        active = store.list_topics(status="active")
        # 2026-08-26: 토픽당 한 문장 요약(haiku 1콜)을 폐기했다. 사용자 요청으로
        # 각 토픽의 '현재 상황' 전문이 본문이 됐고, 그 위에 압축본을 또 얹으면
        # 같은 내용을 두 번 읽게 된다. 요약 품질은 이제 topics.py의 토픽 업데이트
        # 단계(현재 상황 생성)가 전적으로 책임진다.

        dump_paths = topics_mod.write_topic_dumps(active)

        # 당일(쉰 날 포함 창) 발행분 + 본문 요약 문단 + 반영 토픽 — LLM 0회
        try:
            new_reports, window_label = collect_new_reports(today)
        except Exception:
            logger.exception("kcif highlight collection failed — 제목 목록으로 폴백")
            new_reports = [dict(r) for r in store.get_conn().execute(
                "SELECT title, category, md_path FROM reports "
                "WHERE published_date = ? ORDER BY id ASC", (date_s,)).fetchall()]
            window_label = ""

        REPORTS_OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORTS_OUT_DIR / f"{date_s}-kcif-topics.md"
        out.write_text(render_daily(date_s, status, dump_paths, new_reports, window_label),
                       encoding="utf-8")
        # 휴일로 쉬었다가 강제/재실행으로 리포트가 생기면 표지는 낡은 것이다.
        (SKIP_MARKER_DIR / f"{date_s}.json").unlink(missing_ok=True)

        made = _self_heal_periodics(today, dump_paths, status)
        return {"date": date_s, "md_path": str(out), "status": status, "periodics": made}
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
