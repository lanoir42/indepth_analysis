"""KCIF 토픽 타임라인 파이프라인 — telegram topic_tracker 미러 (소스=KCIF 리포트).

매칭: 키워드 LIKE 후보 → haiku 1콜(관련성 필터 + 신규 이벤트 + 롤링 요약).
워터마크 정책 (telegram 미러): 후보 0 → max id로 전진 / LLM 성공 → max(후보 id)
/ LLM 실패 + 후보 존재 → 커서 유지 (다음 실행 재시도).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from indepth_analysis.kcif import llm, store
from indepth_analysis.kcif.paths import KST, PROJECT_ROOT, TOPIC_DUMP_DIR

logger = logging.getLogger(__name__)

CANDIDATE_CAP = 40
EXCERPT_CHARS = 1_200
PROMPT_BUDGET_CHARS = 12_000
TIMELINE_DAYS = 14
TIMELINE_BULLET_CAP = 20
RECENT_CUTOFF_DAYS = 90  # 시드 워터마크 초기화: 이 이전 published_date는 스킵

KEYWORD_EXPAND_SYSTEM = (
    "당신은 국제금융 리서치 아카이브의 토픽 매칭 키워드를 설계합니다. "
    "주어진 토픽에 대해 한국어/영어 혼합 5~10개 키워드를 만드세요. "
    "조사·어미가 붙어도 부분일치로 걸리도록 짧은 어간·고유명사 위주, "
    "너무 일반적인 단어(경제, 시장 등) 제외, 전부 소문자."
)

TOPIC_UPDATE_SYSTEM = (
    "당신은 특정 토픽의 전개를 한국어 타임라인으로 정리하는 국제금융 분석가입니다. "
    "키워드로 뽑힌 KCIF 리포트 후보 중 토픽과 실제로 관련 있는 것만 골라내고, "
    "새 타임라인 이벤트와 '현재 상황' 요약을 만듭니다. 규칙: "
    "(1) 후보 리포트에 없는 사실을 지어내지 말 것. "
    "(2) 기존 타임라인과 중복 이벤트 금지. "
    "(3) 헤드라인은 한 줄 한국어 사실 서술 (120자 이내). "
    "(4) event_date는 해당 리포트의 발행일(YYYY-MM-DD). "
    "(5) report_ids는 반드시 후보 id 중에서만. "
    "(6) summary는 토픽 상황 자체만 서술 (500자 이내) — 선별 과정 언급 금지. "
    "(7) 매수/매도/추천 등 행동 지시 금지."
)


def _kst_today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def expand_keywords(title: str, description: str | None) -> list[str]:
    prompt = f"토픽: {title}\n설명: {description or '(없음)'}\n\n" \
             '{"keywords": ["...", ...]} 형태로.'
    data = llm.call_json(prompt, system=KEYWORD_EXPAND_SYSTEM, model="haiku",
                         timeout=90, required_keys=("keywords",))
    if data:
        kws = [str(k).strip().lower() for k in (data.get("keywords") or [])]
        return [k for k in kws if len(k) >= 2][:10]
    # 폴백: 제목 토큰
    return [t.lower() for t in re.split(r"[^\w가-힣]+", title) if len(t) >= 2][:10]


def register_topic(title: str, description: str | None = None,
                   keywords: list[str] | None = None) -> dict:
    """등록 + 키워드 확장. 워터마크는 '최근 90일 이전' 텍스트를 건너뛰게 초기화
    — 첫 실행이 674건 전체를 스캔하는 폭주 방지 (설계 패널 결정)."""
    cutoff = (datetime.now(KST) - timedelta(days=RECENT_CUTOFF_DAYS)).strftime("%Y-%m-%d")
    wm = store.text_id_before_date(cutoff)
    topic = store.create_topic(title, description, keywords or [], watermark_id=wm)
    expanded = expand_keywords(title, description)
    merged = list(dict.fromkeys([*(k.lower() for k in (keywords or [])), *expanded]))
    store.set_keywords(topic["slug"], merged)
    return store.get_topic(topic["slug"])  # type: ignore[return-value]


def _prompt_candidates(cands: list[dict]) -> tuple[str, list[dict]]:
    """예산 내에서 후보 렌더 (오래된 것부터). 반환: (텍스트, 실제 포함 후보)."""
    used = 0
    included: list[dict] = []
    lines: list[str] = []
    for c in cands:
        excerpt = re.sub(r"\s+", " ", (c["text"] or ""))[:EXCERPT_CHARS]
        line = (f"- id={c['report_id']} | {c.get('published_date') or '?'} | "
                f"[{c.get('category') or '?'}] {c['title']}\n  {excerpt}")
        if used + len(line) > PROMPT_BUDGET_CHARS and included:
            break
        lines.append(line)
        used += len(line)
        included.append(c)
    return "\n".join(lines), included


def update_topic(slug: str) -> dict:
    """증분 업데이트 1회. 반환: {ok, reason, events_added, evidence_added,
    candidates(프롬프트 포함분), scanned(스캔된 후보 전체)}."""
    topic = store.get_topic(slug)
    if not topic:
        return {"slug": slug, "ok": False, "reason": "not_found",
                "events_added": 0, "evidence_added": 0, "candidates": 0, "scanned": 0}
    cands = store.scan_candidates(topic, cap=CANDIDATE_CAP)
    if not cands:
        store.advance_watermark(slug, store.max_text_id())
        return {"slug": slug, "ok": True, "reason": "no_candidates",
                "events_added": 0, "evidence_added": 0, "candidates": 0, "scanned": 0}

    recent_events = store.timeline(slug)[-20:]
    timeline_txt = "\n".join(
        f"- {e['event_date']} — {e['headline']}" for e in recent_events) or "(없음)"
    cand_txt, included = _prompt_candidates(cands)

    prompt = (
        f"토픽: {topic['title']} ({slug})\n"
        f"설명: {topic.get('description') or '(없음)'}\n"
        f"키워드: {', '.join(topic.get('keywords') or [])}\n"
        f"오늘(KST): {_kst_today()}\n\n"
        f"[기존 타임라인 (최근)]\n{timeline_txt}\n\n"
        f"[후보 리포트 {len(included)}건 — 관련 있는 것만 relevant_report_ids로]\n"
        f"{cand_txt}\n\n"
        '응답 형식: {"relevant_report_ids": [int], '
        '"events": [{"event_date": "YYYY-MM-DD", "headline": "...", '
        '"detail": "...", "report_ids": [int]}], "summary": "..."}'
    )
    data = llm.call_json(prompt, system=TOPIC_UPDATE_SYSTEM, model="haiku", timeout=180,
                         required_keys=("relevant_report_ids", "events", "summary"))
    if data is None:
        # LLM 실패 + 후보 존재 → 커서 유지, 다음 실행 재시도 (telegram 정책 미러)
        return {"slug": slug, "ok": False, "reason": "llm_failed",
                "events_added": 0, "evidence_added": 0,
                "candidates": len(included), "scanned": len(cands)}

    by_id = {c["report_id"] for c in included}
    relevant = [int(r) for r in (data.get("relevant_report_ids") or [])
                if isinstance(r, (int, float)) and int(r) in by_id]
    evidence_added = store.add_evidence(slug, relevant)

    events = []
    for e in (data.get("events") or []):
        head = str(e.get("headline") or "").strip()
        day = str(e.get("event_date") or "").strip()
        if not head or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            continue
        rids = [int(r) for r in (e.get("report_ids") or [])
                if isinstance(r, (int, float)) and int(r) in by_id]
        ts = datetime.strptime(day, "%Y-%m-%d").replace(hour=12, tzinfo=KST).timestamp()
        events.append({"event_date": day, "headline": head,
                       "detail": str(e.get("detail") or ""), "report_ids": rids, "ts": ts})
    events_added = store.add_events(slug, events[:8])

    summary = str(data.get("summary") or "").strip()
    if summary:
        store.update_summary(slug, summary)

    store.advance_watermark(slug, max(c["text_id"] for c in included))
    return {"slug": slug, "ok": True, "reason": "ok", "events_added": events_added,
            "evidence_added": evidence_added,
            "candidates": len(included), "scanned": len(cands)}


MAX_BACKLOG_PASSES = 12  # 패스당 프롬프트 예산 내 ~8-10건 소화 → 런당 최대 ~100건/토픽


def update_all() -> list[dict]:
    """전 활성 토픽 업데이트. 후보가 남아 있는 토픽은 이어서 재스캔
    (한 실행에서 큰 백로그를 청크로 소화, 최대 MAX_BACKLOG_PASSES패스).

    2026-08-18 버그픽스: 기존 중단 조건이 `candidates < CAP`이었는데
    candidates는 프롬프트 예산(12k자) 절단 *후* 포함 건수(~9)라 항상
    1패스에서 중단 — 백로그 소화 루프가 한 번도 돌지 않아 토픽들이
    6월 백로그에 두 달 넘게 갇혔다. scanned(절단 전) 기준으로 판단하고,
    남은 후보가 없어질 때(no_candidates)까지 계속한다."""
    results = []
    for t in store.list_topics(status="active"):
        agg = {"slug": t["slug"], "ok": True, "reason": "ok",
               "events_added": 0, "evidence_added": 0, "candidates": 0}
        for _ in range(MAX_BACKLOG_PASSES):
            res = update_topic(t["slug"])
            agg["ok"] = res["ok"]
            agg["reason"] = res["reason"]
            agg["events_added"] += res["events_added"]
            agg["evidence_added"] += res["evidence_added"]
            agg["candidates"] += res["candidates"]
            # 중단: 실패(커서 유지, 다음 실행 재시도) 또는 후보 소진.
            # scanned == candidates 이면서 scanned < CAP 이면 이번 패스로 전부
            # 소화된 것 — 한 패스 더 돌아 no_candidates로 워터마크를 head까지
            # 점프시킨다 (LLM 호출 없는 스캔 1회 비용).
            if not res["ok"] or res["reason"] == "no_candidates":
                break
        results.append(agg)
    return results


# ── 토픽 원문 덤프 (.md — nvim gf 대상) ────────────────────────────────────

def write_topic_dumps(topics: list[dict]) -> dict[str, str]:
    """토픽별 풀 덤프 → {slug: 절대경로}. 매일 덮어쓰는 롤링 파일."""
    paths: dict[str, str] = {}
    TOPIC_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    for t in topics:
        try:
            p = TOPIC_DUMP_DIR / f"{t['slug']}.md"
            p.write_text(_render_dump(t), encoding="utf-8")
            paths[t["slug"]] = str(p)
        except Exception:
            logger.exception("kcif topic dump failed slug=%s", t.get("slug"))
    return paths


def _render_dump(t: dict) -> str:
    slug = t["slug"]
    lines = [
        f"# {t['title']} ({slug}) — KCIF 토픽 원문",
        "",
        "(자동 생성 — 매일 덮어씀. 코멘트는 일간 kcif-topics 리포트에 남기세요)",
        "",
        f"- 키워드: {', '.join(t.get('keywords') or []) or '(없음)'}",
        "",
        "## 현재 상황",
        "",
        (t.get("summary_text") or "").strip() or "(요약 대기)",
        "",
    ]
    events = store.timeline(slug)
    lines.append(f"## 타임라인 (전체 {len(events)}건)")
    lines.append("")
    for e in events:
        lines.append(f"- {e['event_date']} — {e['headline']}")
        if (e.get("detail") or "").strip():
            lines.append(f"    {e['detail'].strip()}")
    if not events:
        lines.append("- (이벤트 없음)")
    lines.append("")
    ev = store.evidence_with_reports(slug, limit=30)
    lines.append(f"## 근거 리포트 (최신 {len(ev)}건)")
    lines.append("")
    for e in ev:
        lines.append(f"- [{e.get('category') or '?'}] {e.get('published_date') or '?'} — {e['title']}")
        if e.get("md_path"):
            lines.append(f"    {PROJECT_ROOT / e['md_path']}")
    if not ev:
        lines.append("- (근거 없음)")
    return "\n".join(lines).rstrip() + "\n"


SEED_TOPICS: list[tuple[str, str]] = [
    ("FOMC·미국 통화정책", "연준 금리 결정·점도표·QT, 미국 통화정책 경로"),
    ("원/달러·외국인 자금흐름", "원/달러 환율, 외국인 주식·채권 자금 유출입, 외환시장 수급"),
    ("중국 경제·정책", "중국 성장률·부양책·부동산·위안화, 인민은행 정책"),
    ("일본 BOJ·엔화", "일본은행 통화정책, YCC, 엔화 환율, 엔캐리"),
    ("미국 재정·국채시장", "미국 재정적자·국채 발행·수급, 장기금리, 부채한도"),
    ("지정학 리스크(중동·우크라이나)", "중동 분쟁, 우크라이나 전쟁, 유가·공급망 파급"),
]


def seed_topics() -> list[str]:
    """시드 토픽 6개 등록 (이미 있으면 스킵). 반환: 등록된 슬러그."""
    added = []
    for title, desc in SEED_TOPICS:
        if store.get_topic(store.slugify(title)):
            continue
        try:
            t = register_topic(title, desc)
            added.append(t["slug"])
        except ValueError as e:
            logger.warning("seed topic skipped %s: %s", title, e)
    return added
