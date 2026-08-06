"""컨텍스트 팩 빌더 — 마스터클래스 Stage 1 결정론 계층.

해설서의 LLM 스테이지가 **숫자를 만들지 않도록**, 이 모듈이 당월 리포트·전월
리포트·로컬 백본 DB에서 필요한 모든 사실 재료를 미리 뽑아 하나의 JSON
(:class:`ContextPack`)으로 고정한다.

구성 요소
---------
1. 당월 리포트 파싱 — 섹션 분해, 섹션별 핵심 수치 문장, 인라인 출처
2. 전월 델타 소재 — 섹션별 (전월 요지, 당월 요지) 쌍 (5장 원료)
3. 백본 시계열 표 — HICP 골든 체인 / 정책금리 24개월 / optionsdeck 장기 계열 /
   서프라이즈 통계 스냅샷 (4장 원료, 표는 전부 코드가 생성)
4. 주제 후보 스코어링 — 리포트 키워드 × 커리큘럼 카탈로그 매칭

하드 제약: **LLM 호출 없음, 네트워크 접근 없음.** 로컬 파일과 로컬 SQLite만
읽으며, optionsdeck 원본 DB는 반드시 어댑터
(:class:`~indepth_analysis.data.optionsdeck_series.OptionsdeckSeriesClient`)를
경유한다. 백본 소스가 없으면 해당 표만 생략하고 ``notes``에 사유를 남긴다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from indepth_analysis.skills.euro_macro.masterclass.curriculum import (
    DEFAULT_REPORTS_DIR,
    MASTERCLASS_DIRNAME,
    TOPIC_CATALOG,
    TopicCandidate,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/macro_calendar.db")

#: 백본 표의 기본 관측 창(개월).
BACKBONE_MONTHS = 24

#: 정책금리 표에 싣는 통화 (국가) 코드.
RATE_COUNTRIES: tuple[str, ...] = ("USD", "EUR", "GBP", "JPY", "KRW")

#: HICP 골든 체인을 구성하는 (지표 제목, 라벨) 쌍.
HICP_CHAIN_TITLES: tuple[tuple[str, str], ...] = (
    ("CPI Flash Estimate y/y", "Flash"),
    ("Final CPI y/y", "Final"),
)

#: optionsdeck 백본 계열 id.
OD_EA_HICP_SERIES = "M.RCH_A.CP00.EA"
OD_VIX_SERIES = "VIXCLS"
OD_BRENT_SERIES = "DCOILBRENTEU"

#: 서프라이즈 통계 스냅샷의 최소 표본 수.
SURPRISE_MIN_HISTORY = 6

#: 섹션 종류별 주제 스코어 가중치.
SECTION_WEIGHTS: dict[str, float] = {
    "body": 1.0,
    "appendix": 0.7,
    "deterministic": 0.3,
    "meta": 0.0,
}

#: 키워드 1개가 한 섹션에서 기여할 수 있는 최대 히트 수 (편중 방지).
MAX_HITS_PER_KEYWORD_PER_SECTION = 5


# --- 리포트 파싱 -------------------------------------------------------------

_H1_RE = re.compile(r"^#\s+(?P<t>.+?)\s*$")
_H2_RE = re.compile(r"^##\s+(?P<t>.+?)\s*$")
_HN_RE = re.compile(r"^#{3,6}\s+(?P<t>.+?)\s*$")
_BODY_HEADING_RE = re.compile(r"^(?P<k>\d{1,2})\.\s*(?P<t>.+)$")
_DET_HEADING_RE = re.compile(r"^(?P<k>[A-H])\.\s*(?P<t>.+)$")
_APPENDIX_HEADING_RE = re.compile(r"^부록\s+(?P<k>[IVXLC]+)\.?\s*(?P<t>.*)$")

#: 최상위로 인정하는 메타 섹션 제목 (부록 내부의 '참고문헌'은 제외 — 부록 V의
#: 하위 절이므로 최상위로 올리면 부록이 잘린다).
META_HEADINGS: frozenset[str] = frozenset({"목차", "참고 자료", "참고자료"})

_INLINE_SOURCE_RE = re.compile(r"\[출처:\s*([^\]]+)\]")
_URL_RE = re.compile(r"https?://[^\s)\]>,]+")

#: 숫자 + 단위 조합 (핵심 수치 문장 판정).
_NUMBER_UNIT_RE = re.compile(
    r"(?:\d[\d,]*(?:\.\d+)?\s*(?:%p|%|bp|bps|pp|배럴|포인트|억|조|만|명|건|"
    r"달러|유로|MWh|mta|배|만톤)|[€$]\s?\d)"
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_SKIP_LINE_PREFIXES = ("|", "#", ">", "---", "===")

MIN_NUMERIC_SENTENCE_LEN = 20
GIST_CHAR_LIMIT = 700


class ReportSectionParse(BaseModel):
    """리포트에서 잘라낸 최상위 섹션 1개."""

    key: str
    heading: str
    kind: str = "body"
    order: int = 0
    text: str = ""
    char_count: int = 0
    subheadings: list[str] = Field(default_factory=list)
    numeric_sentences: list[str] = Field(default_factory=list)
    inline_sources: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @property
    def gist(self) -> str:
        return _gist(self.text)


class SectionDelta(BaseModel):
    """전월 ↔ 당월 섹션 쌍 (5장 '전월과의 대화' 원료)."""

    key: str
    match_kind: str = "key"
    prev_heading: str | None = None
    curr_heading: str | None = None
    prev_gist: str = ""
    curr_gist: str = ""
    prev_numbers: list[str] = Field(default_factory=list)
    curr_numbers: list[str] = Field(default_factory=list)


class BackboneTable(BaseModel):
    """코드가 생성한 결정론적 표 (마크다운 + 구조화 데이터 양쪽)."""

    id: str
    title: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    markdown: str = ""
    source: str = ""
    note: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.rows


class ContextPack(BaseModel):
    """마스터클래스 1강분 결정론 컨텍스트."""

    year: int
    month: int
    generated_at: str = ""
    report_path: str | None = None
    report_title: str = ""
    prev_year: int | None = None
    prev_month: int | None = None
    prev_report_path: str | None = None
    has_prev_month: bool = False
    sections: list[ReportSectionParse] = Field(default_factory=list)
    headline_numbers: list[str] = Field(default_factory=list)
    inline_sources: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    deltas: list[SectionDelta] = Field(default_factory=list)
    backbone_tables: list[BackboneTable] = Field(default_factory=list)
    topic_candidates: list[TopicCandidate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def section(self, key: str) -> ReportSectionParse | None:
        for sec in self.sections:
            if sec.key == key:
                return sec
        return None

    def table(self, table_id: str) -> BackboneTable | None:
        for tbl in self.backbone_tables:
            if tbl.id == table_id:
                return tbl
        return None

    @property
    def report_text(self) -> str:
        return "\n\n".join(s.text for s in self.sections)


def _gist(text: str, limit: int = GIST_CHAR_LIMIT) -> str:
    """섹션 앞부분을 문장 경계로 잘라 요지 문자열을 만든다."""
    body = " ".join(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith(_SKIP_LINE_PREFIXES)
    )
    if len(body) <= limit:
        return body
    cut = body[:limit]
    tail = max(cut.rfind("다."), cut.rfind(". "))
    if tail > limit // 2:
        cut = cut[: tail + 1]
    return cut.rstrip() + "…"


def split_sentences(text: str) -> list[str]:
    """표·헤딩 줄을 제외하고 문장 단위로 자른다."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(_SKIP_LINE_PREFIXES):
            continue
        for part in _SENTENCE_SPLIT_RE.split(stripped):
            cleaned = part.strip(" \t-•*")
            if cleaned:
                out.append(cleaned)
    return out


def extract_numeric_sentences(text: str) -> list[str]:
    """숫자+단위를 포함한 문장만 추려 반환 (중복 제거, 원문 순서 유지)."""
    seen: set[str] = set()
    out: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence) < MIN_NUMERIC_SENTENCE_LEN:
            continue
        if not _NUMBER_UNIT_RE.search(sentence):
            continue
        if sentence in seen:
            continue
        seen.add(sentence)
        out.append(sentence)
    return out


def extract_inline_sources(text: str) -> list[str]:
    """``[출처: …]`` 인라인 출처를 중복 없이 반환."""
    out: list[str] = []
    for raw in _INLINE_SOURCE_RE.findall(text):
        for part in raw.split(";"):
            item = part.strip()
            if item and item not in out:
                out.append(item)
    return out


def extract_source_urls(text: str) -> list[str]:
    """본문 내 URL을 중복 없이 반환."""
    out: list[str] = []
    for url in _URL_RE.findall(text):
        cleaned = url.rstrip(".,)")
        if cleaned not in out:
            out.append(cleaned)
    return out


def _classify_heading(title: str, zone: str) -> tuple[str, str, str] | None:
    """``(key, kind, heading)``을 반환하거나, 최상위가 아니면 ``None``.

    부록/결정론 섹션(A~H)에 진입한 뒤로는 숫자 헤딩(``## 1. …``)이 부록 내부의
    하위 절이므로 최상위로 승격하지 않는다 (부록 III·V가 자체 ``## 1.`` 구조를
    갖기 때문 — 실물 2026-08.md에서 확인).
    """
    appendix = _APPENDIX_HEADING_RE.match(title)
    if appendix:
        return f"부록 {appendix.group('k')}", "appendix", title
    if title in META_HEADINGS:
        return title, "meta", title
    det = _DET_HEADING_RE.match(title)
    if det and zone in {"body", "deterministic"}:
        return det.group("k"), "deterministic", title
    body = _BODY_HEADING_RE.match(title)
    if body and zone == "body":
        return body.group("k"), "body", title
    return None


def parse_report_markdown(text: str) -> tuple[str, list[ReportSectionParse]]:
    """리포트 마크다운을 (제목, 최상위 섹션 목록)으로 분해한다."""
    lines = text.splitlines()
    title = ""
    sections: list[ReportSectionParse] = []
    zone = "body"
    current: dict[str, Any] | None = None
    buf: list[str] = []
    used_keys: set[str] = set()

    def flush() -> None:
        nonlocal current, buf
        if current is None:
            buf = []
            return
        body = "\n".join(buf).strip()
        section = ReportSectionParse(
            key=current["key"],
            heading=current["heading"],
            kind=current["kind"],
            order=len(sections),
            text=body,
            char_count=len(body),
            subheadings=current["subheadings"],
            numeric_sentences=extract_numeric_sentences(body),
            inline_sources=extract_inline_sources(body),
            source_urls=extract_source_urls(body),
        )
        sections.append(section)
        current = None
        buf = []

    for line in lines:
        h1 = _H1_RE.match(line)
        if h1 and not title and current is None:
            title = h1.group("t")
            continue
        h2 = _H2_RE.match(line)
        if h2:
            classified = _classify_heading(h2.group("t"), zone)
            if classified is not None:
                key, kind, heading = classified
                flush()
                if kind == "appendix":
                    zone = "appendix"
                elif kind == "deterministic" and zone == "body":
                    zone = "deterministic"
                unique = key
                suffix = 2
                while unique in used_keys:
                    unique = f"{key}#{suffix}"
                    suffix += 1
                used_keys.add(unique)
                current = {
                    "key": unique,
                    "heading": heading,
                    "kind": kind,
                    "subheadings": [],
                }
                continue
            if current is not None:
                current["subheadings"].append(h2.group("t"))
            buf.append(line)
            continue
        hn = _HN_RE.match(line)
        if hn and current is not None:
            current["subheadings"].append(hn.group("t"))
        if current is not None:
            buf.append(line)
    flush()
    return title, sections


# --- 전월 델타 ---------------------------------------------------------------


def _normalize_heading(heading: str) -> str:
    return re.sub(r"\s+", " ", heading).strip().lower()


_HEADING_PREFIX_RE = re.compile(r"^(?:\d{1,2}|[A-H]|부록\s+[IVXLC]+)\.\s*")

#: 키가 같아도 제목이 이만큼도 닮지 않으면 다른 섹션으로 본다.
HEADING_SIMILARITY_THRESHOLD = 0.25


def _heading_bigrams(heading: str) -> set[str]:
    text = _HEADING_PREFIX_RE.sub("", _normalize_heading(heading))
    text = re.sub(r"[^0-9a-z가-힣]+", "", text)
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def _heading_similarity(a: str, b: str) -> float:
    """제목 문자 bigram Jaccard 유사도 (0.0~1.0)."""
    left, right = _heading_bigrams(a), _heading_bigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def build_deltas(
    current: Sequence[ReportSectionParse],
    previous: Sequence[ReportSectionParse],
) -> list[SectionDelta]:
    """섹션별 (전월 요지, 당월 요지) 쌍을 만든다.

    매칭 순서: 헤딩 완전 일치 → 섹션 키 일치(+제목 유사도 게이트) → 미매칭
    (신규/소멸). 리포트 포맷이 달 사이에 바뀌면 키가 같아도 전혀 다른 섹션이
    될 수 있으므로 (2026-07의 '1. 핵심 요약' vs 2026-08의 '1. 통화정책 및 금리
    동향'), 제목이 :data:`HEADING_SIMILARITY_THRESHOLD` 미만으로 닮았으면 짝을
    짓지 않는다 — 엉뚱한 쌍은 5장에서 없는 서사 변화를 만들어내기 때문이다.
    """
    if not previous:
        return []
    prev_by_heading = {_normalize_heading(s.heading): s for s in previous}
    prev_by_key = {s.key: s for s in previous}
    consumed: set[int] = set()
    deltas: list[SectionDelta] = []

    def take(sec: ReportSectionParse | None) -> ReportSectionParse | None:
        if sec is None or id(sec) in consumed:
            return None
        consumed.add(id(sec))
        return sec

    for sec in current:
        if sec.kind == "meta":
            continue
        match = take(prev_by_heading.get(_normalize_heading(sec.heading)))
        match_kind = "heading"
        if match is None:
            by_key = prev_by_key.get(sec.key)
            if by_key is not None and (
                _heading_similarity(by_key.heading, sec.heading)
                >= HEADING_SIMILARITY_THRESHOLD
            ):
                match = take(by_key)
                match_kind = "key"
        if match is None:
            deltas.append(
                SectionDelta(
                    key=sec.key,
                    match_kind="new",
                    curr_heading=sec.heading,
                    curr_gist=sec.gist,
                    curr_numbers=sec.numeric_sentences[:6],
                )
            )
            continue
        deltas.append(
            SectionDelta(
                key=sec.key,
                match_kind=match_kind,
                prev_heading=match.heading,
                curr_heading=sec.heading,
                prev_gist=match.gist,
                curr_gist=sec.gist,
                prev_numbers=match.numeric_sentences[:6],
                curr_numbers=sec.numeric_sentences[:6],
            )
        )

    for sec in previous:
        if sec.kind == "meta" or id(sec) in consumed:
            continue
        deltas.append(
            SectionDelta(
                key=sec.key,
                match_kind="dropped",
                prev_heading=sec.heading,
                prev_gist=sec.gist,
                prev_numbers=sec.numeric_sentences[:6],
            )
        )
    return deltas


# --- 주제 스코어링 -----------------------------------------------------------


def score_topic_candidates(
    sections: Sequence[ReportSectionParse],
    *,
    top_n: int = 12,
) -> list[TopicCandidate]:
    """리포트 텍스트 × 커리큘럼 카탈로그 키워드 매칭 점수를 계산한다.

    점수 = Σ(섹션 가중치 × 키워드 등장 횟수). 키워드 1개가 한 섹션에서 기여할
    수 있는 히트는 :data:`MAX_HITS_PER_KEYWORD_PER_SECTION`로 상한을 둔다.
    최종 주제 확정은 LLM(Stage 2)이 하며, 여기서는 근거와 순위만 제공한다.
    """
    hits: dict[str, dict[str, int]] = {}
    scores: dict[str, float] = {}
    where: dict[str, list[str]] = {}

    for sec in sections:
        weight = SECTION_WEIGHTS.get(sec.kind, 0.0)
        if weight <= 0 or not sec.text:
            continue
        text = sec.text
        for topic_id, spec in TOPIC_CATALOG.items():
            section_hit = False
            for keyword in spec.keywords:
                count = text.count(keyword)
                if not count:
                    continue
                capped = min(count, MAX_HITS_PER_KEYWORD_PER_SECTION)
                hits.setdefault(topic_id, {})
                hits[topic_id][keyword] = hits[topic_id].get(keyword, 0) + capped
                scores[topic_id] = scores.get(topic_id, 0.0) + capped * weight
                section_hit = True
            if section_hit:
                where.setdefault(topic_id, []).append(sec.key)

    candidates = [
        TopicCandidate(
            topic_id=topic_id,
            title_ko=TOPIC_CATALOG[topic_id].title_ko,
            track=TOPIC_CATALOG[topic_id].track,
            score=round(score, 2),
            keyword_hits=hits.get(topic_id, {}),
            sections=where.get(topic_id, []),
        )
        for topic_id, score in scores.items()
    ]
    candidates.sort(key=lambda c: (-c.score, c.topic_id))
    return candidates[:top_n]


# --- 백본 표 -----------------------------------------------------------------


def render_markdown_table(
    columns: Sequence[str], rows: Sequence[dict[str, Any]]
) -> str:
    """구조화 행을 마크다운 표 문자열로 렌더링한다."""
    if not rows:
        return ""
    head = "| " + " | ".join(columns) + " |"
    sep = "|" + "|".join("---" for _ in columns) + "|"
    body = [
        "| "
        + " | ".join(
            "" if row.get(col) is None else str(row.get(col)) for col in columns
        )
        + " |"
        for row in rows
    ]
    return "\n".join([head, sep, *body])


def _make_table(
    table_id: str,
    title: str,
    columns: Sequence[str],
    rows: Sequence[dict[str, Any]],
    source: str,
    note: str = "",
) -> BackboneTable:
    return BackboneTable(
        id=table_id,
        title=title,
        columns=list(columns),
        rows=list(rows),
        markdown=render_markdown_table(columns, rows),
        source=source,
        note=note,
    )


def _month_end(year: int, month: int) -> date:
    first_next = (
        date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    )
    return first_next - timedelta(days=1)


def _recent_months(year: int, month: int, count: int) -> list[tuple[int, int]]:
    """``(year, month)``로 끝나는 ``count``개월의 (연, 월) 목록 (오름차순)."""
    total = year * 12 + (month - 1)
    out: list[tuple[int, int]] = []
    for offset in range(count - 1, -1, -1):
        y, m_idx = divmod(total - offset, 12)
        out.append((y, m_idx + 1))
    return out


def _fmt(value: float | None, digits: int = 2, suffix: str = "") -> str | None:
    if value is None:
        return None
    return f"{value:.{digits}f}{suffix}"


def build_hicp_chain_table(store: Any, year: int, month: int) -> BackboneTable:
    """EUR HICP flash/final 발표 체인 (released only, 출처 표기 포함)."""
    rows: list[dict[str, Any]] = []
    end = datetime.combine(_month_end(year, month), datetime.max.time(), tzinfo=UTC)
    for title, label in HICP_CHAIN_TITLES:
        series = store.get_indicator_series("EUR", title, released_only=True)
        for event in series.events:
            if event.actual is None:
                continue
            when = event.datetime_utc
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            if when > end:
                continue
            rows.append(
                {
                    "발표일": when.date().isoformat(),
                    "지표": label,
                    "실제": _fmt(event.actual, 1, "%"),
                    "예상": _fmt(event.forecast, 1, "%"),
                    "이전": _fmt(event.previous, 1, "%"),
                    "서프라이즈": _fmt(event.surprise, 1, "%p"),
                    "출처": event.source,
                }
            )
    rows.sort(key=lambda r: (str(r["발표일"]), str(r["지표"])))
    return _make_table(
        "hicp_golden_chain",
        "유로존 HICP 발표 체인 (Flash / Final, 실제치)",
        ["발표일", "지표", "실제", "예상", "이전", "서프라이즈", "출처"],
        rows,
        source="MacroStore.calendar_events (EUR, released only)",
        note=(
            "출처 컬럼의 golden:eurostat / json+golden:r6 는 Eurostat 1차 확인분, "
            "seed:jblanked 는 벤더 시드 행이다 (혼재는 정상)."
        ),
    )


def build_policy_rate_table(
    store: Any, year: int, month: int, months: int = BACKBONE_MONTHS
) -> BackboneTable:
    """주요 5개 중앙은행 정책금리 월말 수준 (carry-forward)."""
    from bgilib.macro.constants import CB_NAMES, COUNTRY_LABELS_KOR

    histories: dict[str, list[Any]] = {}
    for country in RATE_COUNTRIES:
        try:
            histories[country] = store.get_rate_history(country)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("rate history 조회 실패 %s: %s", country, exc)
            histories[country] = []

    columns = ["기준월"] + [
        f"{COUNTRY_LABELS_KOR.get(c, c)}({CB_NAMES.get(c, c)})"
        for c in RATE_COUNTRIES
    ]
    rows: list[dict[str, Any]] = []
    for y, m in _recent_months(year, month, months):
        cutoff = _month_end(y, m)
        row: dict[str, Any] = {"기준월": f"{y}-{m:02d}"}
        for country in RATE_COUNTRIES:
            label = (
                f"{COUNTRY_LABELS_KOR.get(country, country)}"
                f"({CB_NAMES.get(country, country)})"
            )
            level = None
            for decision in histories[country]:
                if decision.date_utc <= cutoff:
                    level = decision.rate_pct
                else:
                    break
            row[label] = _fmt(level, 2, "%")
        rows.append(row)
    return _make_table(
        "policy_rate_24m",
        f"주요국 정책금리 월말 수준 (최근 {months}개월)",
        columns,
        rows,
        source="MacroStore.rate_decisions (FRED / OECD MEI)",
        note="각 월 말일 기준 유효 금리 (마지막 관측치 carry-forward).",
    )


def build_surprise_stats_table(
    store: Any, year: int, month: int, min_n: int = SURPRISE_MIN_HISTORY
) -> BackboneTable:
    """서프라이즈 분포 스냅샷 (표본 n ≥ min_n 그룹만)."""
    from indepth_analysis.skills.euro_macro.macro_alerts import surprise_stats

    before = datetime.combine(
        _month_end(year, month), datetime.max.time(), tzinfo=UTC
    )
    stats = surprise_stats(store, before=before, min_history_points=min_n)
    rows = [
        {
            "국가": st.country,
            "지표": st.title,
            "표본수": st.n,
            "평균 서프라이즈": _fmt(st.mean, 3),
            "표준편차(σ)": _fmt(st.sigma, 3),
        }
        for st in sorted(
            stats.values(), key=lambda s: (-s.n, s.country, s.title)
        )
    ]
    return _make_table(
        "surprise_stats",
        f"지표별 서프라이즈 분포 (최근 24개월, 표본 n≥{min_n})",
        ["국가", "지표", "표본수", "평균 서프라이즈", "표준편차(σ)"],
        rows,
        source="macro_alerts.surprise_stats(MacroStore)",
        note=(
            "z = (서프라이즈 − 평균) / σ. 평균이 0이 아닌 것은 컨센서스의 "
            "체계적 편향을 뜻한다."
        ),
    )


def _parse_period(label: str) -> date | None:
    """optionsdeck 계열의 이질적 기간 라벨을 날짜로 정규화."""
    text = label.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
        if re.fullmatch(r"\d{4}-\d{2}", text):
            y, m = text.split("-")
            return _month_end(int(y), int(m))
    except ValueError:
        return None
    return None


def _observations(client: Any, series_id: str) -> list[tuple[date, float]]:
    rows = client.get_series(series_id)
    out: list[tuple[date, float]] = []
    for obs in rows:
        when = _parse_period(str(getattr(obs, "date", "")))
        value = getattr(obs, "value", None)
        if when is None or value is None:
            continue
        out.append((when, float(value)))
    out.sort(key=lambda pair: pair[0])
    return out


def build_ea_hicp_long_table(
    client: Any, year: int, month: int, months: int = BACKBONE_MONTHS
) -> BackboneTable:
    """optionsdeck EA HICP 장기 계열 — 최근 구간 표 + 장기 위치 각주."""
    obs = [
        pair
        for pair in _observations(client, OD_EA_HICP_SERIES)
        if pair[0] <= _month_end(year, month)
    ]
    recent = obs[-months:]
    rows = [
        {"기준월": f"{d.year}-{d.month:02d}", "EA HICP y/y": _fmt(v, 1, "%")}
        for d, v in recent
    ]
    note = ""
    if obs:
        values = [v for _, v in obs]
        latest_date, latest = obs[-1]
        below = sum(1 for v in values if v <= latest)
        pct = 100.0 * below / len(values)
        hi_date, hi = max(obs, key=lambda p: p[1])
        lo_date, lo = min(obs, key=lambda p: p[1])
        note = (
            f"장기 표본 {len(values)}개월 ({obs[0][0].isoformat()}~"
            f"{obs[-1][0].isoformat()}), 평균 {sum(values) / len(values):.2f}%, "
            f"최고 {hi:.1f}% ({hi_date.year}-{hi_date.month:02d}), "
            f"최저 {lo:.1f}% ({lo_date.year}-{lo_date.month:02d}). "
            f"최신 관측 {latest:.1f}% "
            f"({latest_date.year}-{latest_date.month:02d})는 장기 분포의 "
            f"{pct:.0f}백분위."
        )
    return _make_table(
        "ea_hicp_long",
        f"유로존 HICP 연간변화율 장기 계열 (최근 {months}개월 + 장기 위치)",
        ["기준월", "EA HICP y/y"],
        rows,
        source=f"optionsdeck 백본 {OD_EA_HICP_SERIES} (DBnomics/Eurostat)",
        note=note,
    )


def build_vix_brent_table(
    client: Any, year: int, month: int, months: int = BACKBONE_MONTHS
) -> BackboneTable:
    """optionsdeck VIX·브렌트 월말값 (최근 24개월)."""
    vix = dict(
        ((d.year, d.month), v) for d, v in _observations(client, OD_VIX_SERIES)
    )
    brent = dict(
        ((d.year, d.month), v) for d, v in _observations(client, OD_BRENT_SERIES)
    )
    rows: list[dict[str, Any]] = []
    for y, m in _recent_months(year, month, months):
        rows.append(
            {
                "기준월": f"{y}-{m:02d}",
                "VIX (월말)": _fmt(vix.get((y, m)), 2),
                "Brent $/bbl (월말)": _fmt(brent.get((y, m)), 2),
            }
        )
    return _make_table(
        "vix_brent_24m",
        f"VIX·브렌트유 월말값 (최근 {months}개월)",
        ["기준월", "VIX (월말)", "Brent $/bbl (월말)"],
        rows,
        source=(
            f"optionsdeck 백본 {OD_VIX_SERIES} / {OD_BRENT_SERIES} (FRED, "
            "월 마지막 관측치)"
        ),
        note="백본 수집기는 하루 2회 갱신 — 당월 값은 최신 영업일 기준일 수 있다.",
    )


def _open_optionsdeck(notes: list[str]) -> Any | None:
    """optionsdeck 어댑터를 열고 available() 게이트를 통과하면 반환."""
    try:
        from indepth_analysis.data.optionsdeck_series import (
            OptionsdeckSeriesClient,
        )
    except Exception as exc:
        notes.append(f"optionsdeck 어댑터 임포트 실패 — 장기 계열 표 생략 ({exc})")
        return None
    try:
        client = OptionsdeckSeriesClient()
        info = client.available()
    except Exception as exc:
        notes.append(f"optionsdeck 스냅샷 실패 — 장기 계열 표 생략 ({exc})")
        return None
    if not info:
        reason = getattr(info, "reason", None) or "unavailable"
        notes.append(f"optionsdeck 백본 사용 불가 — 장기 계열 표 생략 ({reason})")
        return None
    return client


def build_backbone_tables(
    year: int,
    month: int,
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    optionsdeck_client: Any | None = None,
    notes: list[str] | None = None,
) -> list[BackboneTable]:
    """4장용 백본 표 전체를 만든다 (소스 부재 시 해당 표만 생략)."""
    notes = notes if notes is not None else []
    tables: list[BackboneTable] = []

    path = Path(db_path)
    if not path.exists():
        notes.append(
            f"매크로 캘린더 DB 없음 — HICP/정책금리/서프라이즈 표 생략 ({path})"
        )
    else:
        try:
            from bgilib.macro.storage import MacroStore

            store = MacroStore(path)
        except Exception as exc:
            notes.append(f"MacroStore 열기 실패 — DB 기반 표 생략 ({exc})")
            store = None
        if store is not None:
            for builder in (
                build_hicp_chain_table,
                build_policy_rate_table,
                build_surprise_stats_table,
            ):
                try:
                    tables.append(builder(store, year, month))
                except Exception as exc:  # pragma: no cover - defensive
                    notes.append(f"{builder.__name__} 실패 — 표 생략 ({exc})")

    client = optionsdeck_client
    if client is None:
        client = _open_optionsdeck(notes)
    else:
        probe = getattr(client, "available", None)
        if probe is not None:
            try:
                if not probe():
                    notes.append("optionsdeck 백본 사용 불가 — 장기 계열 표 생략")
                    client = None
            except Exception as exc:
                notes.append(f"optionsdeck available() 실패 — 표 생략 ({exc})")
                client = None
    if client is not None:
        for builder in (build_ea_hicp_long_table, build_vix_brent_table):
            try:
                tables.append(builder(client, year, month))
            except Exception as exc:
                notes.append(f"{builder.__name__} 실패 — 표 생략 ({exc})")

    kept: list[BackboneTable] = []
    for table in tables:
        if table.is_empty:
            notes.append(f"{table.id} 표 비어 있음 — 컨텍스트 팩에서 제외")
            continue
        kept.append(table)
    return kept


# --- 조립 / 직렬화 -----------------------------------------------------------


def report_path_for(year: int, month: int, reports_dir: Path | str) -> Path:
    return Path(reports_dir) / f"{year}-{month:02d}.md"


def default_context_path(
    year: int, month: int, reports_dir: Path | str = DEFAULT_REPORTS_DIR
) -> Path:
    return (
        Path(reports_dir)
        / MASTERCLASS_DIRNAME
        / f"{year}-{month:02d}-context.json"
    )


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _dedupe(items: Iterable[str], limit: int) -> list[str]:
    out: list[str] = []
    for item in items:
        if item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def build_context_pack(
    year: int,
    month: int,
    *,
    reports_dir: Path | str = DEFAULT_REPORTS_DIR,
    db_path: Path | str = DEFAULT_DB_PATH,
    optionsdeck_client: Any | None = None,
) -> ContextPack:
    """당월 리포트 + 전월 델타 + 백본 표 + 주제 후보를 하나로 묶어 반환한다.

    Args:
        year: 리포트 연도.
        month: 리포트 월.
        reports_dir: ``{Y}-{MM}.md``가 있는 디렉터리.
        db_path: bgilib 매크로 캘린더 SQLite 경로.
        optionsdeck_client: 테스트용 주입 지점. ``None``이면 실제 어댑터를
            열되 ``available()`` 게이트를 통과하지 못하면 조용히 생략한다.

    Raises:
        FileNotFoundError: 당월 리포트 마크다운이 없을 때.
    """
    notes: list[str] = []
    path = report_path_for(year, month, reports_dir)
    if not path.exists():
        raise FileNotFoundError(f"당월 리포트가 없습니다: {path}")
    text = path.read_text(encoding="utf-8")
    title, sections = parse_report_markdown(text)

    prev_y, prev_m = _prev_month(year, month)
    prev_path = report_path_for(prev_y, prev_m, reports_dir)
    prev_sections: list[ReportSectionParse] = []
    if prev_path.exists():
        _, prev_sections = parse_report_markdown(
            prev_path.read_text(encoding="utf-8")
        )
    else:
        notes.append(
            f"전월 리포트 없음 — 델타 비움 (제1강 경로): {prev_path.name}"
        )

    deltas = build_deltas(sections, prev_sections)
    paired = [d for d in deltas if d.match_kind in {"heading", "key"}]
    if prev_sections and not paired:
        notes.append(
            "전월 리포트와 섹션 제목이 일치하지 않음 (포맷 변경) — 짝지어진 "
            "델타 없음, 신규/소멸 목록으로만 제공"
        )

    headline = _dedupe(
        (
            sentence
            for sec in sections
            if sec.kind == "body"
            for sentence in sec.numeric_sentences
        ),
        limit=60,
    )
    inline_sources = _dedupe(
        (src for sec in sections for src in sec.inline_sources), limit=200
    )
    urls = _dedupe((u for sec in sections for u in sec.source_urls), limit=200)

    tables = build_backbone_tables(
        year,
        month,
        db_path=db_path,
        optionsdeck_client=optionsdeck_client,
        notes=notes,
    )

    return ContextPack(
        year=year,
        month=month,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        report_path=str(path),
        report_title=title,
        prev_year=prev_y if prev_sections else None,
        prev_month=prev_m if prev_sections else None,
        prev_report_path=str(prev_path) if prev_sections else None,
        has_prev_month=bool(prev_sections),
        sections=sections,
        headline_numbers=headline,
        inline_sources=inline_sources,
        source_urls=urls,
        deltas=deltas,
        backbone_tables=tables,
        topic_candidates=score_topic_candidates(sections),
        notes=notes,
    )


def save_context_pack(
    pack: ContextPack,
    path: Path | str | None = None,
    *,
    reports_dir: Path | str = DEFAULT_REPORTS_DIR,
) -> Path:
    """컨텍스트 팩을 JSON으로 저장하고 경로를 반환한다."""
    target = (
        Path(path)
        if path is not None
        else default_context_path(pack.year, pack.month, reports_dir)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(pack.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def load_context_pack(path: Path | str) -> ContextPack:
    """저장된 컨텍스트 팩 JSON을 로드한다."""
    return ContextPack.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
