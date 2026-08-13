"""KCIF 일간/월간/분기 리포트 파이프라인 (18:00 KST launchd 잡의 본체).

무인 운영 원칙 (설계 패널):
- 각 단계(크롤/다운로드/추출/토픽/LLM) 개별 격리 — 어떤 실패에도 일간 리포트
  파일은 **무조건** 생성되고, ``## 실행 상태`` 섹션이 결정적으로 렌더되어
  orchestrator 저널이 곧 장애 알림 채널이 된다.
- 월간/분기는 별도 스케줄이 아니라 매 실행의 자가치유 체크(전월/전분기 파일
  부재 시 생성) — launchd misfire·전원 off에 강건.
- 인터랙티브 절대 금지 (nvim 등) — cron-safe.
"""

from __future__ import annotations

import fcntl
import logging
import random
import time
from datetime import date as date_cls
from datetime import datetime, timedelta

from indepth_analysis.kcif import llm, store, topics as topics_mod
from indepth_analysis.kcif.paths import KST, LOCK_PATH, PDF_DIR, PROJECT_ROOT, REPORTS_OUT_DIR

logger = logging.getLogger(__name__)

DOWNLOAD_CAP_PER_RUN = 50
DOWNLOAD_RECENT_DAYS = 14   # PENDING 재시도 대상 published_date 윈도우
FAILED_RETRY_DAYS = 7       # FAILED → PENDING 리셋 윈도우
SLEEP_BASE_S = 0.7

EXEC_SUMMARY_SYSTEM = (
    "당신은 KCIF 토픽 트래킹 리포트의 Executive summary를 쓰는 분석가입니다. "
    "각 토픽의 '현황/변화'를 객관적·건조하게 정확히 1문장(120자 이내)으로 요약합니다. "
    "오늘 신규 이벤트가 있으면 그 변화를 우선 서술하고, 없으면 '변화 없음'을 명시. "
    "제공된 정보에 없는 사실 금지, 매수/매도/추천 금지."
)

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


# ── Executive summary ──────────────────────────────────────────────────────

def _build_exec_summary(active: list[dict], date_str: str) -> list[str]:
    day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=KST).timestamp()
    parts = [f"오늘(KST): {date_str}", "", "[토픽 목록]"]
    for t in active:
        evs = [e["headline"] for e in store.timeline(t["slug"])
               if float(e.get("created_ts") or 0) >= day_start][:5]
        parts.append(f"- slug={t['slug']} | 제목={t['title']}")
        parts.append(f"  현재 요약: {(t.get('summary_text') or '').strip()[:300] or '(요약 없음)'}")
        parts.append(f"  오늘 신규: {' / '.join(evs) if evs else '(오늘 신규 이벤트 없음)'}")
    parts.append('\n응답 형식: {"lines": [{"slug": "...", "line": "..."}]}')
    data = llm.call_json("\n".join(parts), system=EXEC_SUMMARY_SYSTEM, model="haiku",
                         timeout=120, required_keys=("lines",))
    by_slug = {}
    if data:
        for item in (data.get("lines") or []):
            s, line = str(item.get("slug") or ""), str(item.get("line") or "").strip()
            if s and line:
                by_slug[s] = line
    out = []
    for t in active:
        line = by_slug.get(t["slug"])
        if not line:
            summary = (t.get("summary_text") or "").strip()
            line = (summary.split(". ")[0][:120] + "…") if len(summary) > 120 else (summary or "(요약 대기)")
        out.append(f"- **{t['title']}**: {line}")
    return out


# ── 렌더 ───────────────────────────────────────────────────────────────────

def _date_minus(date_str: str, days: int) -> str:
    return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


def render_daily(date_str: str, status: dict, exec_lines: list[str],
                 dump_paths: dict[str, str], new_reports: list[dict]) -> str:
    active = store.list_topics(status="active")
    lines = [
        f"# KCIF 토픽 타임라인 — {date_str}",
        "",
        f"활성 토픽 {len(active)}개 — KCIF(국제금융센터) 리포트 기반 자동 추적 타임라인입니다.",
        "",
        "## 실행 상태",
        "",
    ]
    for key, label in (("crawl", "크롤"), ("download", "다운로드"),
                       ("extract", "텍스트 추출"), ("topics", "토픽 업데이트"),
                       ("exec", "요약")):
        lines.append(f"- {label}: {status.get(key, '실행 안 됨')}")
    lines.append("")

    if exec_lines:
        lines.append("## Executive summary")
        lines.append("")
        lines.extend(exec_lines)
        lines.append("")

    lines.append(f"## 오늘 신규 리포트 ({len(new_reports)}건)")
    lines.append("")
    if new_reports:
        for r in new_reports[:30]:
            lines.append(f"- **[{r.get('category') or '?'}] {r['title']}**")
            if r.get("md_path"):
                lines.append(str(PROJECT_ROOT / r["md_path"]))
    else:
        lines.append("- 오늘 수집된 신규 리포트가 없습니다.")
    lines.append("")

    cutoff = _date_minus(date_str, 13)  # 최근 14일 윈도우
    for t in active:
        slug = t["slug"]
        lines.append(f"## {t['title']} ({slug})")
        lines.append("")
        summary = (t.get("summary_text") or "").strip() or "(요약 대기 — 아직 수집된 근거가 없습니다)"
        lines.append(f"- **현재 상황**: {summary}")
        events = store.timeline(slug)
        recent = [e for e in events if str(e.get("event_date") or "") >= cutoff]
        older = len(events) - len(recent)
        if len(recent) > 20:
            older += len(recent) - 20
            recent = recent[-20:]
        lines.append("- **타임라인**:")
        if recent:
            for e in recent:
                lines.append(f"- {e['event_date']} — {e['headline']}")
        else:
            lines.append("- 최근 14일 신규 이벤트 없음")
        if older:
            lines.append(f"- (이전 이벤트 {older}건 — 원문 파일 참조)")
        ev = store.evidence_stats(slug)
        cats = ", ".join(f"{c} {n}건" for c, n in ev["categories"]) or "(없음)"
        lines.append(f"- **근거**: 총 {ev['total']}건 — 카테고리: {cats}")
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
                   dump_paths: dict[str, str]) -> str:
    """월간/분기 공용 렌더 — prefixes: event_date가 시작해야 하는 YYYY-MM 목록."""
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
            system=MONTHLY_SYNTH_SYSTEM, model="sonnet", timeout=300)
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
        body = _render_period(f"KCIF 월간 타임라인 — {ym}", f"{ym} 한 달간", [ym], dump_paths)
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

def run_daily(date_str: str | None = None, *, skip_crawl: bool = False) -> dict:
    """18:00 KST 잡 본체. 어떤 단계가 실패해도 일간 리포트는 생성된다."""
    today = _today_kst() if not date_str else datetime.strptime(date_str, "%Y-%m-%d").date()
    date_s = today.isoformat()

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
        if skip_crawl:
            status["crawl"] = status["download"] = status["extract"] = "스킵 (--skip-crawl)"
        else:
            try:
                _crawl_and_ingest(status, today)
            except Exception as e:
                logger.exception("kcif crawl stage failed")
                status.setdefault("crawl", f"실패 — {str(e)[:120]}")
                status.setdefault("download", "크롤 실패로 미실행")
                status.setdefault("extract", "크롤 실패로 미실행")

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
        try:
            exec_lines = _build_exec_summary(active, date_s)
            status["exec"] = "성공"
        except Exception as e:
            logger.exception("kcif exec summary failed")
            exec_lines = [f"- **{t['title']}**: {(t.get('summary_text') or '(요약 대기)')[:120]}"
                          for t in active]
            status["exec"] = f"실패(폴백) — {str(e)[:80]}"

        dump_paths = topics_mod.write_topic_dumps(active)

        # 오늘 신규 리포트 (published_date == 오늘, md 있는 것 우선)
        conn = store.get_conn()
        new_reports = [dict(r) for r in conn.execute(
            "SELECT title, category, md_path FROM reports "
            "WHERE published_date = ? ORDER BY id ASC", (date_s,)).fetchall()]

        REPORTS_OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORTS_OUT_DIR / f"{date_s}-kcif-topics.md"
        out.write_text(render_daily(date_s, status, exec_lines, dump_paths, new_reports),
                       encoding="utf-8")

        made = _self_heal_periodics(today, dump_paths, status)
        return {"date": date_s, "md_path": str(out), "status": status, "periodics": made}
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
