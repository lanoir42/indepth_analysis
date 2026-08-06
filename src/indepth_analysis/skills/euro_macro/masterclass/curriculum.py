"""누적 커리큘럼 상태 — 마스터클래스 Stage 1 결정론 계층.

해설서는 매월 1강씩 쌓이는 커리큘럼이므로, "무엇을 이미 가르쳤나"를 상태 파일로
추적해야 매월 기초를 반복하지 않고 심화로 올라갈 수 있다. 이 모듈은 그 상태
(:class:`CurriculumState`)의 스키마·로드/저장·주제 선정·상태 전이·예측 매칭을
모두 결정론적으로 제공한다. **LLM 호출도 네트워크 접근도 없다** — 최종 주제 확정과
예측 채점은 Stage 2/3의 LLM이 하고, 여기서는 후보와 소재만 만든다.

주요 공개 API
-------------
``initial_state()``          제1강용 시드 상태 (토픽 큐 = 설계 문서 순환 큐)
``load_state(path)``         상태 로드 (파일 없으면 시드 상태)
``save_state(state, path)``  상태 저장 (부모 디렉터리 자동 생성)
``select_topics(...)``       이달 주제 후보 → 매크로 n개 + 정치 n개 선정
``record_lecture(...)``      강 생성 후 상태 전이 (새 상태 반환, 입력 불변)
``resolve_predictions(...)`` 전월 예측 × 당월 리포트 텍스트 매칭 소재
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Track = Literal["macro", "politics"]
Depth = Literal["intro", "core", "advanced"]
ReaderLevel = Literal["foundation", "intermediate", "advanced"]

#: 심화 승급 순서. 재방문 시 한 단계씩 올라간다.
DEPTH_ORDER: tuple[Depth, ...] = ("intro", "core", "advanced")

DEFAULT_REPORTS_DIR = Path("reports/euro_macro")
MASTERCLASS_DIRNAME = "masterclass"
DEFAULT_STATE_PATH = (
    DEFAULT_REPORTS_DIR / MASTERCLASS_DIRNAME / "curriculum_state.json"
)

#: 독자 수준 자동 승급 임계값 (커버 주제 수 기준).
READER_LEVEL_THRESHOLDS: tuple[tuple[int, ReaderLevel], ...] = (
    (15, "advanced"),
    (6, "intermediate"),
    (0, "foundation"),
)


# --- 주제 카탈로그 -----------------------------------------------------------


@dataclass(frozen=True)
class TopicSpec:
    """커리큘럼 주제 1개의 정적 정의.

    ``keywords``는 리포트 본문에서 이 주제가 이달 사건으로 등장했는지 판정하는
    결정론적 신호다 (context_pack의 주제 스코어링이 소비).
    """

    id: str
    title_ko: str
    track: Track
    keywords: tuple[str, ...]


_TOPIC_SPECS: tuple[TopicSpec, ...] = (
    # --- 매크로 트랙 ---
    TopicSpec(
        id="ecb-policy-mechanics",
        title_ko="ECB 정책금리 메커니즘 — DFR·MRO·MLF 3금리와 전달경로",
        track="macro",
        keywords=(
            "ECB",
            "예금금리",
            "정책금리",
            "재융자금리",
            "한계대출",
            "DFR",
            "정책위원회",
            "인상",
            "동결",
            "인하",
            "bp",
        ),
    ),
    TopicSpec(
        id="ois-curve-reading",
        title_ko="OIS 커브에서 정책 확률 읽기 — 시장 기반 기대의 문법과 한계",
        track="macro",
        keywords=(
            "OIS",
            "확률",
            "시장은",
            "반영",
            "프라이싱",
            "선물",
            "기대",
            "컨센서스",
        ),
    ),
    TopicSpec(
        id="hicp-anatomy",
        title_ko="HICP의 내부 — flash/final, 코어, 항목별 기여도",
        track="macro",
        keywords=(
            "HICP",
            "인플레이션",
            "물가",
            "속보치",
            "확정치",
            "코어",
            "근원",
            "서비스",
            "비에너지",
            "Eurostat",
        ),
    ),
    TopicSpec(
        id="base-effect-arithmetic",
        title_ko="기저효과의 산술 — 전년동월비와 모멘텀 분해",
        track="macro",
        keywords=(
            "기저효과",
            "전년동월",
            "전년동기",
            "y/y",
            "전월비",
            "m/m",
            "모멘텀",
            "연율",
        ),
    ),
    TopicSpec(
        id="sovereign-spread",
        title_ko="국채 스프레드의 해부 — BTP-Bund와 벤치마크의 의미",
        track="macro",
        keywords=(
            "스프레드",
            "BTP",
            "분트",
            "Bund",
            "국채금리",
            "10년물",
            "국채시장",
            "리스크 프리미엄",
        ),
    ),
    TopicSpec(
        id="yield-curve-term-premium",
        title_ko="수익률 곡선과 기간 프리미엄 — 커브가 말하는 것",
        track="macro",
        keywords=(
            "수익률 곡선",
            "장단기",
            "2년물",
            "기간 프리미엄",
            "커브",
            "역전",
        ),
    ),
    TopicSpec(
        id="tpi-fragmentation",
        title_ko="TPI와 단편화 방지 장치 — ECB 대차대조표 정책",
        track="macro",
        keywords=(
            "TPI",
            "단편화",
            "PEPP",
            "APP",
            "재투자",
            "양적긴축",
            "QT",
            "대차대조표",
        ),
    ),
    TopicSpec(
        id="energy-inflation-passthrough",
        title_ko="에너지→인플레이션 전달경로 — TTF·유가·전기요금의 사슬",
        track="macro",
        keywords=(
            "TTF",
            "가스",
            "LNG",
            "유가",
            "브렌트",
            "에너지",
            "전기요금",
            "저장고",
            "호르무즈",
        ),
    ),
    TopicSpec(
        id="labour-market-indicators",
        title_ko="노동시장 지표 해부 — 실업률·협상임금·결원율",
        track="macro",
        keywords=(
            "실업률",
            "고용",
            "임금",
            "협상임금",
            "청년실업",
            "노동시장",
            "실업자",
        ),
    ),
    TopicSpec(
        id="pmi-anatomy",
        title_ko="PMI 해부 — 확산지수의 문법과 오독 위험",
        track="macro",
        keywords=(
            "PMI",
            "구매관리자",
            "확산지수",
            "제조업",
            "서비스업",
            "종합지수",
            "Ifo",
        ),
    ),
    TopicSpec(
        id="gdp-accounting",
        title_ko="GDP 계정 해부 — 지출·재고·순수출과 속보치의 한계",
        track="macro",
        keywords=(
            "GDP",
            "성장률",
            "전분기",
            "속보치",
            "재고",
            "순수출",
            "내수",
            "잠재성장",
        ),
    ),
    TopicSpec(
        id="fx-passthrough",
        title_ko="환율 전달경로 — EUR/USD와 수입물가·기업이익",
        track="macro",
        keywords=(
            "EUR/USD",
            "환율",
            "유로화",
            "절상",
            "절하",
            "달러",
            "강세",
            "약세",
        ),
    ),
    TopicSpec(
        id="bank-lending-channel",
        title_ko="은행 대출경로와 BLS — 통화정책이 실물에 닿는 길",
        track="macro",
        keywords=(
            "BLS",
            "대출태도",
            "신용기준",
            "은행",
            "여신",
            "대출",
            "주택담보",
        ),
    ),
    TopicSpec(
        id="credit-spreads-nbfi",
        title_ko="신용 스프레드와 비은행 금융(NBFI) — 그림자 레버리지",
        track="macro",
        keywords=(
            "사모신용",
            "NBFI",
            "비은행",
            "신용 스프레드",
            "회사채",
            "금융안정",
            "FSR",
        ),
    ),
    TopicSpec(
        id="equity-market-structure",
        title_ko="유럽 주식시장 구조 — STOXX 600 섹터 구성과 매크로 민감도",
        track="macro",
        keywords=(
            "STOXX",
            "증시",
            "주가지수",
            "섹터",
            "사상 최고",
            "위험선호",
            "실적",
        ),
    ),
    TopicSpec(
        id="balance-of-payments",
        title_ko="경상수지·무역수지 읽기 — 유로존 대외 포지션",
        track="macro",
        keywords=(
            "무역수지",
            "경상수지",
            "수출",
            "수입",
            "무역",
            "공급망",
        ),
    ),
    TopicSpec(
        id="inflation-expectations",
        title_ko="기대인플레이션 — 서베이 vs 시장(5y5y)의 괴리",
        track="macro",
        keywords=(
            "기대인플레",
            "5y5y",
            "인플레이션 스왑",
            "SPF",
            "서베이",
            "2차 효과",
            "2차 파급",
        ),
    ),
    TopicSpec(
        id="fiscal-impulse",
        title_ko="재정 임펄스와 국채 발행 — 조달비용의 매크로 되먹임",
        track="macro",
        keywords=(
            "재정적자",
            "차입",
            "국채 발행",
            "재정 확장",
            "국방 지출",
            "국방비",
            "부채비율",
        ),
    ),
    # --- 정치·제도 트랙 ---
    TopicSpec(
        id="eu-institutions",
        title_ko="EU 기관 구조 — 집행위·이사회·의회의 3각 입법",
        track="politics",
        keywords=(
            "집행위",
            "이사회",
            "유럽의회",
            "EU",
            "브뤼셀",
            "폰데어라이엔",
            "거버넌스",
        ),
    ),
    TopicSpec(
        id="ecb-governance",
        title_ko="ECB 지배구조 — 정책위원회·집행이사회·회원국 총재의 정치",
        track="politics",
        keywords=(
            "정책위원회",
            "집행이사회",
            "총재",
            "라가르드",
            "매파",
            "비둘기",
            "만장일치",
        ),
    ),
    TopicSpec(
        id="sgp-fiscal-rules",
        title_ko="EU 재정규칙(SGP)과 과다적자시정절차(EDP)",
        track="politics",
        keywords=(
            "SGP",
            "재정준칙",
            "재정규칙",
            "EDP",
            "과다적자",
            "부채제동",
            "복구기금",
        ),
    ),
    TopicSpec(
        id="france-institutions",
        title_ko="프랑스 제5공화국의 제도 역학 — 결선투표·동거정부",
        track="politics",
        keywords=(
            "프랑스",
            "RN",
            "마크롱",
            "르펜",
            "바르델라",
            "국민연합",
            "앙상블",
            "대선",
        ),
    ),
    TopicSpec(
        id="germany-institutions",
        title_ko="독일 연방제와 연정 정치 — 부채제동의 헌법 정치",
        track="politics",
        keywords=(
            "독일",
            "AfD",
            "CDU",
            "CSU",
            "메르츠",
            "연정",
            "연방",
            "분데스탁",
        ),
    ),
    TopicSpec(
        id="italy-institutions",
        title_ko="이탈리아 정치제도 — 연정 불안정과 재정 신뢰",
        track="politics",
        keywords=(
            "이탈리아",
            "멜로니",
            "FdI",
            "이탈리아형제당",
            "민주당",
        ),
    ),
    TopicSpec(
        id="spain-institutions",
        title_ko="스페인 정치제도 — 소수정부와 지역정당 연합",
        track="politics",
        keywords=(
            "스페인",
            "산체스",
            "PP",
            "Vox",
            "카탈루냐",
        ),
    ),
    TopicSpec(
        id="election-calendar",
        title_ko="유럽 선거 캘린더와 정치 리스크 프리미엄",
        track="politics",
        keywords=(
            "선거",
            "총선",
            "여론조사",
            "지지율",
            "불신임",
            "조기 총선",
            "정권교체",
        ),
    ),
    TopicSpec(
        id="eu-enlargement-east",
        title_ko="EU 확대와 중·동유럽 정치 — 조건부성의 작동",
        track="politics",
        keywords=(
            "헝가리",
            "오르반",
            "루마니아",
            "폴란드",
            "체코",
            "확대",
            "법치",
        ),
    ),
    TopicSpec(
        id="eu-trade-policy",
        title_ko="EU 통상정책 결정구조 — 관세·무역방어 수단",
        track="politics",
        keywords=(
            "관세",
            "통상",
            "무역협정",
            "무역방어",
            "보복",
            "미·EU",
            "트럼프",
        ),
    ),
    TopicSpec(
        id="defence-integration",
        title_ko="유럽 방위통합과 조달 정치 — NATO·EU의 이중 구조",
        track="politics",
        keywords=(
            "방산",
            "국방",
            "나토",
            "NATO",
            "우크라이나",
            "방위",
            "조달",
        ),
    ),
)

#: ``{topic_id: TopicSpec}`` — 주제 정의의 단일 진실 원천.
TOPIC_CATALOG: dict[str, TopicSpec] = {spec.id: spec for spec in _TOPIC_SPECS}

#: 제1강 시드 큐. 설계 문서의 순환 큐(매크로 심화 1~2 + 정치 1) 순서를 반영해
#: 매크로/정치를 번갈아 배치한다. 큐 순서는 후보 점수가 동률일 때의 tie-break.
INITIAL_TOPIC_QUEUE: tuple[str, ...] = (
    "ecb-policy-mechanics",
    "ois-curve-reading",
    "ecb-governance",
    "hicp-anatomy",
    "energy-inflation-passthrough",
    "france-institutions",
    "sovereign-spread",
    "base-effect-arithmetic",
    "sgp-fiscal-rules",
    "pmi-anatomy",
    "labour-market-indicators",
    "germany-institutions",
    "gdp-accounting",
    "fx-passthrough",
    "eu-institutions",
    "inflation-expectations",
    "tpi-fragmentation",
    "italy-institutions",
    "bank-lending-channel",
    "credit-spreads-nbfi",
    "election-calendar",
    "fiscal-impulse",
    "equity-market-structure",
    "eu-trade-policy",
    "balance-of-payments",
    "yield-curve-term-premium",
    "eu-enlargement-east",
    "spain-institutions",
    "defence-integration",
)


def topics_for_track(track: Track) -> list[str]:
    """카탈로그에서 ``track`` 트랙 주제 id 목록을 반환."""
    return [spec.id for spec in _TOPIC_SPECS if spec.track == track]


# --- 상태 모델 ---------------------------------------------------------------


class CoveredTopic(BaseModel):
    """이미 강의한 주제 1건."""

    id: str
    title_ko: str = ""
    lecture: int = 0
    depth: Depth = "intro"


class GlossaryEntry(BaseModel):
    """누적 용어사전 항목."""

    lecture: int = 0
    definition_ko: str = ""


class Prediction(BaseModel):
    """6장에서 제시한 예측 질문 (다음 강 5장에서 채점)."""

    made_in: int = 0
    question: str
    checkpoints: list[str] = Field(default_factory=list)
    resolution: str | None = None


class CurriculumState(BaseModel):
    """커리큘럼 누적 상태 — ``curriculum_state.json``의 스키마."""

    lecture_no: int = 0
    covered_topics: list[CoveredTopic] = Field(default_factory=list)
    topic_queue: list[str] = Field(default_factory=list)
    glossary: dict[str, GlossaryEntry] = Field(default_factory=dict)
    reader_level: ReaderLevel = "foundation"
    predictions: list[Prediction] = Field(default_factory=list)

    def covered_index(self) -> dict[str, CoveredTopic]:
        """``{topic_id: CoveredTopic}`` 조회용 인덱스."""
        return {t.id: t for t in self.covered_topics}

    def is_covered(self, topic_id: str) -> bool:
        return any(t.id == topic_id for t in self.covered_topics)


class TopicCandidate(BaseModel):
    """리포트 텍스트에서 결정론적으로 뽑은 이달 주제 후보.

    :mod:`context_pack`의 스코어러가 생산하고 :func:`select_topics`가 소비한다.
    """

    topic_id: str
    title_ko: str = ""
    track: Track = "macro"
    score: float = 0.0
    keyword_hits: dict[str, int] = Field(default_factory=dict)
    sections: list[str] = Field(default_factory=list)

    @property
    def evidence(self) -> list[str]:
        """근거 키워드 (빈도 내림차순)."""
        return [
            kw
            for kw, _ in sorted(
                self.keyword_hits.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ]


class SelectedTopic(BaseModel):
    """이달 강의로 확정 제안된 주제 1건."""

    id: str
    title_ko: str
    track: Track
    depth: Depth = "intro"
    revisit: bool = False
    score: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""


class TopicSelection(BaseModel):
    """:func:`select_topics` 결과 — 트랙별 선정 주제."""

    macro: list[SelectedTopic] = Field(default_factory=list)
    politics: list[SelectedTopic] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def all_topics(self) -> list[SelectedTopic]:
        return [*self.macro, *self.politics]


class PredictionMatch(BaseModel):
    """전월 예측 × 당월 리포트 매칭 소재 (채점은 LLM이 5장에서)."""

    prediction: Prediction
    matched: bool = False
    matched_terms: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


# --- 로드 / 저장 -------------------------------------------------------------


def initial_state() -> CurriculumState:
    """제1강용 시드 상태 (lecture_no=0, 큐만 채워진 상태)."""
    return CurriculumState(
        lecture_no=0,
        covered_topics=[],
        topic_queue=list(INITIAL_TOPIC_QUEUE),
        glossary={},
        reader_level="foundation",
        predictions=[],
    )


def load_state(path: Path | str = DEFAULT_STATE_PATH) -> CurriculumState:
    """상태 파일을 로드한다. 파일이 없으면 :func:`initial_state`를 반환.

    큐에 남은 항목 중 카탈로그에 없는 id는 조용히 버리고, 카탈로그에 있으나
    큐에도 covered에도 없는 주제는 큐 끝에 덧붙인다 (카탈로그 확장 대응).
    """
    p = Path(path)
    if not p.exists():
        return initial_state()
    state = CurriculumState.model_validate_json(p.read_text(encoding="utf-8"))
    return _reconcile_with_catalog(state)


def save_state(
    state: CurriculumState, path: Path | str = DEFAULT_STATE_PATH
) -> Path:
    """상태를 JSON으로 저장하고 경로를 반환 (부모 디렉터리 자동 생성)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            state.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return p


def _reconcile_with_catalog(state: CurriculumState) -> CurriculumState:
    """큐를 현재 카탈로그와 정합화 (미지 id 제거 + 신규 주제 append)."""
    covered = {t.id for t in state.covered_topics}
    queue = [tid for tid in state.topic_queue if tid in TOPIC_CATALOG]
    seen = set(queue)
    for tid in INITIAL_TOPIC_QUEUE:
        if tid not in seen and tid not in covered:
            queue.append(tid)
            seen.add(tid)
    new = state.model_copy(deep=True)
    new.topic_queue = queue
    return new


# --- 주제 선정 ---------------------------------------------------------------


def _next_depth(current: Depth) -> Depth:
    idx = DEPTH_ORDER.index(current)
    return DEPTH_ORDER[min(idx + 1, len(DEPTH_ORDER) - 1)]


def _spec(topic_id: str) -> TopicSpec | None:
    return TOPIC_CATALOG.get(topic_id)


def _select_track(
    state: CurriculumState,
    candidates: Sequence[TopicCandidate],
    track: Track,
    n: int,
    notes: list[str],
) -> list[SelectedTopic]:
    """한 트랙에서 ``n``개 주제를 선정한다.

    우선순위:
        1. 후보(리포트 사건) ∩ 큐(미커버) — 점수 내림차순
        2. 큐 순서 (사건 근거는 없지만 커리큘럼상 다음 주제)
        3. 큐 소진 시 커버된 주제 재방문 — depth 승급 (intro→core→advanced),
           후보 점수 높은 것 우선, 동률이면 가장 오래된 강의부터
    """
    if n <= 0:
        return []
    covered = state.covered_index()
    queue = [
        tid
        for tid in state.topic_queue
        if tid in TOPIC_CATALOG
        and TOPIC_CATALOG[tid].track == track
        and tid not in covered
    ]
    queue_set = set(queue)
    scores = {c.topic_id: c for c in candidates if c.topic_id in TOPIC_CATALOG}

    picked: list[SelectedTopic] = []
    used: set[str] = set()

    ranked = sorted(
        (c for c in candidates if c.topic_id in queue_set and c.score > 0),
        key=lambda c: (-c.score, state.topic_queue.index(c.topic_id)),
    )
    for cand in ranked:
        if len(picked) >= n:
            break
        spec = _spec(cand.topic_id)
        if spec is None or cand.topic_id in used:
            continue
        picked.append(
            SelectedTopic(
                id=spec.id,
                title_ko=spec.title_ko,
                track=track,
                depth="intro",
                revisit=False,
                score=cand.score,
                evidence=cand.evidence[:8],
                reason="이달 리포트 사건 매칭 + 미커버 큐",
            )
        )
        used.add(cand.topic_id)

    for tid in queue:
        if len(picked) >= n:
            break
        if tid in used:
            continue
        spec = _spec(tid)
        if spec is None:
            continue
        cand = scores.get(tid)
        picked.append(
            SelectedTopic(
                id=spec.id,
                title_ko=spec.title_ko,
                track=track,
                depth="intro",
                revisit=False,
                score=cand.score if cand else 0.0,
                evidence=cand.evidence[:8] if cand else [],
                reason="큐 순서 (사건 매칭 없음)",
            )
        )
        used.add(tid)

    if len(picked) < n:
        revisitable = [
            t
            for t in state.covered_topics
            if t.id in TOPIC_CATALOG
            and TOPIC_CATALOG[t.id].track == track
            and t.id not in used
        ]
        if revisitable:
            notes.append(
                f"{track} 트랙 큐 소진 — 커버 주제 재방문(depth 승급)으로 보충"
            )
        revisitable.sort(
            key=lambda t: (
                -(scores[t.id].score if t.id in scores else 0.0),
                DEPTH_ORDER.index(t.depth),
                t.lecture,
            )
        )
        for topic in revisitable:
            if len(picked) >= n:
                break
            spec = _spec(topic.id)
            if spec is None:
                continue
            cand = scores.get(topic.id)
            depth = _next_depth(topic.depth)
            picked.append(
                SelectedTopic(
                    id=spec.id,
                    title_ko=spec.title_ko,
                    track=track,
                    depth=depth,
                    revisit=True,
                    score=cand.score if cand else 0.0,
                    evidence=cand.evidence[:8] if cand else [],
                    reason=(
                        f"재방문 — 제{topic.lecture}강 {topic.depth} → {depth} 승급"
                    ),
                )
            )
            used.add(topic.id)

    if len(picked) < n:
        notes.append(f"{track} 트랙 후보 부족 — {len(picked)}/{n}개만 선정")
    return picked


def select_topics(
    state: CurriculumState,
    candidates: Sequence[TopicCandidate],
    n_macro: int = 2,
    n_politics: int = 1,
) -> TopicSelection:
    """이달 주제를 트랙별로 선정한다 (결정론적 제안 — 최종 확정은 LLM).

    Args:
        state: 현재 커리큘럼 상태.
        candidates: :mod:`context_pack`이 만든 이달 사건 기반 주제 후보.
        n_macro: 매크로 트랙 주제 수.
        n_politics: 정치·제도 트랙 주제 수.
    """
    notes: list[str] = []
    macro = _select_track(state, candidates, "macro", n_macro, notes)
    politics = _select_track(state, candidates, "politics", n_politics, notes)
    return TopicSelection(macro=macro, politics=politics, notes=notes)


# --- 상태 전이 ---------------------------------------------------------------


def _reader_level(covered_count: int) -> ReaderLevel:
    for threshold, level in READER_LEVEL_THRESHOLDS:
        if covered_count >= threshold:
            return level
    return "foundation"


def record_lecture(
    state: CurriculumState,
    topics: Sequence[SelectedTopic],
    new_glossary: Mapping[str, str | GlossaryEntry | Mapping[str, object]]
    | None = None,
    predictions: Sequence[Prediction | Mapping[str, object]] | None = None,
) -> CurriculumState:
    """강 생성 후 상태를 전이시킨 **새 상태**를 반환한다 (입력은 불변).

    전이 규칙:
        * ``lecture_no`` +1
        * 강의한 주제를 ``covered_topics``에 upsert (depth·lecture 갱신) 후
          ``topic_queue``에서 제거
        * 용어는 **병합** — 이미 있는 용어의 최초 강 번호·정의는 유지하고
          (정의가 비어 있을 때만 채움) 신규 용어만 추가
        * 예측은 ``made_in``을 새 강 번호로 강제해 append
        * ``reader_level``은 누적 커버 주제 수로 자동 승급
    """
    new = state.model_copy(deep=True)
    new.lecture_no = state.lecture_no + 1

    index = {t.id: t for t in new.covered_topics}
    for topic in topics:
        existing = index.get(topic.id)
        if existing is None:
            spec = TOPIC_CATALOG.get(topic.id)
            title = topic.title_ko or (spec.title_ko if spec else topic.id)
            entry = CoveredTopic(
                id=topic.id,
                title_ko=title,
                lecture=new.lecture_no,
                depth=topic.depth,
            )
            new.covered_topics.append(entry)
            index[topic.id] = entry
        else:
            existing.lecture = new.lecture_no
            if DEPTH_ORDER.index(topic.depth) > DEPTH_ORDER.index(existing.depth):
                existing.depth = topic.depth
            if topic.title_ko:
                existing.title_ko = topic.title_ko
    taught = {t.id for t in topics}
    new.topic_queue = [tid for tid in new.topic_queue if tid not in taught]

    for term, value in (new_glossary or {}).items():
        entry = _coerce_glossary_entry(value, new.lecture_no)
        current = new.glossary.get(term)
        if current is None:
            new.glossary[term] = entry
        elif not current.definition_ko and entry.definition_ko:
            current.definition_ko = entry.definition_ko

    for raw in predictions or []:
        pred = (
            raw
            if isinstance(raw, Prediction)
            else Prediction.model_validate(dict(raw))
        )
        new.predictions.append(
            pred.model_copy(update={"made_in": new.lecture_no})
        )

    new.reader_level = _reader_level(len(new.covered_topics))
    return new


def _coerce_glossary_entry(
    value: str | GlossaryEntry | Mapping[str, object], lecture: int
) -> GlossaryEntry:
    if isinstance(value, GlossaryEntry):
        entry = value.model_copy(deep=True)
        if not entry.lecture:
            entry.lecture = lecture
        return entry
    if isinstance(value, Mapping):
        entry = GlossaryEntry.model_validate(dict(value))
        if not entry.lecture:
            entry.lecture = lecture
        return entry
    return GlossaryEntry(lecture=lecture, definition_ko=str(value))


# --- 예측 매칭 ---------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z가-힣%€$/.]+")
_STOPWORDS = frozenset(
    {
        "그리고",
        "그러나",
        "이번",
        "이는",
        "있다",
        "한다",
        "예상",
        "여부",
        "경우",
        "수준",
        "대비",
        "이상",
        "이하",
        "관련",
        "전망",
        "될까",
        "할까",
        "인가",
        "인지",
    }
)


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in _TOKEN_SPLIT.split(text):
        tok = raw.strip(".")
        if len(tok) < 2 or tok in _STOPWORDS:
            continue
        out.append(tok)
    return out


def resolve_predictions(
    state: CurriculumState,
    report_text: str,
    *,
    max_evidence: int = 5,
) -> list[PredictionMatch]:
    """미해결 예측을 당월 리포트 텍스트와 매칭해 채점 **소재**를 반환한다.

    채점(정답/오답 판정)은 하지 않는다 — LLM이 5장에서 수행한다. 여기서는
    예측 질문·체크포인트의 토큰이 등장하는 리포트 문장을 근거로 전달할 뿐이다.

    매칭 규칙: 체크포인트 문자열이 그대로 포함되면 즉시 매칭. 아니면 질문·
    체크포인트 토큰(길이 2+ , 불용어 제외) 중 2개 이상이 한 문장에 등장할 때
    매칭 (토큰이 1개뿐인 예측은 1개 일치로 충분).
    """
    unresolved = [p for p in state.predictions if p.resolution is None]
    if not unresolved:
        return []
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(report_text) if s.strip()]

    results: list[PredictionMatch] = []
    for pred in unresolved:
        terms: list[str] = []
        for token in _tokens(pred.question):
            if token not in terms:
                terms.append(token)
        for checkpoint in pred.checkpoints:
            for token in _tokens(checkpoint):
                if token not in terms:
                    terms.append(token)
        need = 1 if len(terms) <= 1 else 2

        evidence: list[str] = []
        matched_terms: list[str] = []
        for sentence in sentences:
            direct = any(
                cp.strip() and cp.strip() in sentence for cp in pred.checkpoints
            )
            hits = [t for t in terms if t in sentence]
            if direct or len(hits) >= need:
                if sentence not in evidence:
                    evidence.append(sentence)
                for hit in hits:
                    if hit not in matched_terms:
                        matched_terms.append(hit)
            if len(evidence) >= max_evidence:
                break
        results.append(
            PredictionMatch(
                prediction=pred,
                matched=bool(evidence),
                matched_terms=matched_terms,
                evidence=evidence,
            )
        )
    return results
