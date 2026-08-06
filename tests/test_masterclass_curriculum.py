"""Tests for the masterclass cumulative curriculum state (Stage 1, deterministic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from indepth_analysis.skills.euro_macro.masterclass.curriculum import (
    DEPTH_ORDER,
    INITIAL_TOPIC_QUEUE,
    TOPIC_CATALOG,
    CoveredTopic,
    CurriculumState,
    GlossaryEntry,
    Prediction,
    SelectedTopic,
    TopicCandidate,
    initial_state,
    load_state,
    record_lecture,
    resolve_predictions,
    save_state,
    select_topics,
    topics_for_track,
)


def _candidate(topic_id: str, score: float) -> TopicCandidate:
    spec = TOPIC_CATALOG[topic_id]
    return TopicCandidate(
        topic_id=topic_id,
        title_ko=spec.title_ko,
        track=spec.track,
        score=score,
        keyword_hits={spec.keywords[0]: 5},
        sections=["1"],
    )


# --- 카탈로그 / 시드 ---------------------------------------------------------


def test_initial_state_seeds_queue_with_both_tracks() -> None:
    state = initial_state()
    assert state.lecture_no == 0
    assert state.covered_topics == []
    assert state.reader_level == "foundation"
    assert len(state.topic_queue) >= 20
    assert set(state.topic_queue) <= set(TOPIC_CATALOG)
    macro = topics_for_track("macro")
    politics = topics_for_track("politics")
    assert len(macro) >= 12
    assert len(politics) >= 8
    # 설계 문서의 국가·제도 순환 큐와 매크로 기본 주제가 모두 시드에 있어야 한다.
    for required in (
        "ecb-policy-mechanics",
        "ois-curve-reading",
        "hicp-anatomy",
        "sovereign-spread",
        "sgp-fiscal-rules",
        "france-institutions",
        "germany-institutions",
        "italy-institutions",
        "spain-institutions",
        "eu-institutions",
        "ecb-governance",
        "election-calendar",
        "tpi-fragmentation",
        "energy-inflation-passthrough",
        "labour-market-indicators",
        "pmi-anatomy",
        "fx-passthrough",
    ):
        assert required in INITIAL_TOPIC_QUEUE


# --- 주제 선정 ---------------------------------------------------------------


def test_select_topics_prefers_scored_candidates_in_queue() -> None:
    state = initial_state()
    candidates = [
        _candidate("energy-inflation-passthrough", 90.0),
        _candidate("sovereign-spread", 60.0),
        _candidate("ecb-policy-mechanics", 10.0),
        _candidate("france-institutions", 55.0),
        _candidate("italy-institutions", 20.0),
    ]
    selection = select_topics(state, candidates, n_macro=2, n_politics=1)

    assert [t.id for t in selection.macro] == [
        "energy-inflation-passthrough",
        "sovereign-spread",
    ]
    assert [t.id for t in selection.politics] == ["france-institutions"]
    assert all(t.depth == "intro" for t in selection.all_topics)
    assert all(not t.revisit for t in selection.all_topics)
    assert selection.macro[0].evidence  # 근거 키워드가 실려 있어야 함


def test_select_topics_falls_back_to_queue_order_without_candidates() -> None:
    state = initial_state()
    selection = select_topics(state, [], n_macro=2, n_politics=1)
    assert len(selection.macro) == 2
    assert len(selection.politics) == 1
    assert selection.macro[0].id == "ecb-policy-mechanics"  # 큐 첫 매크로 주제
    assert selection.macro[0].reason.startswith("큐 순서")


def test_select_topics_revisits_with_depth_promotion_when_queue_empty() -> None:
    macro_ids = topics_for_track("macro")
    state = CurriculumState(
        lecture_no=9,
        covered_topics=[
            CoveredTopic(id=tid, title_ko=TOPIC_CATALOG[tid].title_ko,
                         lecture=i + 1, depth="intro")
            for i, tid in enumerate(macro_ids)
        ],
        topic_queue=[t for t in INITIAL_TOPIC_QUEUE if t not in macro_ids],
    )
    selection = select_topics(
        state, [_candidate("hicp-anatomy", 80.0)], n_macro=2, n_politics=0
    )
    assert len(selection.macro) == 2
    assert selection.macro[0].id == "hicp-anatomy"
    assert all(t.revisit for t in selection.macro)
    assert all(t.depth == "core" for t in selection.macro)
    assert any("재방문" in note for note in selection.notes)


def test_select_topics_never_repeats_covered_topic_at_intro() -> None:
    state = initial_state()
    state = record_lecture(
        state,
        [
            SelectedTopic(
                id="hicp-anatomy",
                title_ko=TOPIC_CATALOG["hicp-anatomy"].title_ko,
                track="macro",
            )
        ],
    )
    selection = select_topics(
        state, [_candidate("hicp-anatomy", 999.0)], n_macro=2, n_politics=1
    )
    assert "hicp-anatomy" not in [t.id for t in selection.macro]


# --- 상태 전이 ---------------------------------------------------------------


def test_record_lecture_transitions_state_without_mutating_input() -> None:
    state = initial_state()
    topics = [
        SelectedTopic(
            id="ecb-policy-mechanics",
            title_ko=TOPIC_CATALOG["ecb-policy-mechanics"].title_ko,
            track="macro",
            depth="intro",
        ),
        SelectedTopic(
            id="france-institutions",
            title_ko=TOPIC_CATALOG["france-institutions"].title_ko,
            track="politics",
            depth="intro",
        ),
    ]
    new = record_lecture(
        state,
        topics,
        {"DFR": "ECB 예금금리 (Deposit Facility Rate)"},
        [Prediction(question="9월 ECB는 인상할까?", checkpoints=["9월 ECB", "2.50%"])],
    )

    assert state.lecture_no == 0 and not state.covered_topics  # 입력 불변
    assert new.lecture_no == 1
    assert {t.id for t in new.covered_topics} == {
        "ecb-policy-mechanics",
        "france-institutions",
    }
    assert "ecb-policy-mechanics" not in new.topic_queue
    assert new.glossary["DFR"].lecture == 1
    assert new.predictions[0].made_in == 1
    assert new.predictions[0].resolution is None


def test_record_lecture_merges_glossary_and_promotes_reader_level() -> None:
    state = initial_state()
    state = record_lecture(
        state,
        [SelectedTopic(id="hicp-anatomy", title_ko="HICP", track="macro")],
        {"DFR": "제1강 정의"},
    )
    ids = [t for t in topics_for_track("macro") if t != "hicp-anatomy"][:6]
    state = record_lecture(
        state,
        [SelectedTopic(id=i, title_ko=TOPIC_CATALOG[i].title_ko, track="macro")
         for i in ids],
        {"DFR": "제2강 재정의", "OIS": "익일물 인덱스 스왑"},
    )
    assert state.lecture_no == 2
    assert state.glossary["DFR"].lecture == 1  # 최초 강 번호 유지
    assert state.glossary["DFR"].definition_ko == "제1강 정의"  # 덮어쓰지 않음
    assert state.glossary["OIS"].lecture == 2
    assert len(state.covered_topics) == 7
    assert state.reader_level == "intermediate"


def test_record_lecture_upgrades_depth_on_revisit() -> None:
    state = record_lecture(
        initial_state(),
        [SelectedTopic(id="hicp-anatomy", title_ko="HICP", track="macro")],
    )
    state = record_lecture(
        state,
        [
            SelectedTopic(
                id="hicp-anatomy",
                title_ko="HICP",
                track="macro",
                depth="core",
                revisit=True,
            )
        ],
    )
    covered = state.covered_index()["hicp-anatomy"]
    assert covered.depth == "core"
    assert covered.lecture == 2
    assert len(state.covered_topics) == 1
    assert DEPTH_ORDER.index(covered.depth) == 1


# --- 예측 매칭 ---------------------------------------------------------------


def test_resolve_predictions_matches_checkpoints_in_report_text() -> None:
    state = CurriculumState(
        lecture_no=1,
        predictions=[
            Prediction(
                made_in=1,
                question="9월 ECB 회의에서 예금금리가 인상될까?",
                checkpoints=["예금금리 2.50%", "ECB 9월"],
            ),
            Prediction(
                made_in=1,
                question="스웨덴 릭스방크는 인하할까?",
                checkpoints=["릭스방크 인하"],
            ),
        ],
    )
    report = (
        "ECB는 9월 회의에서 예금금리를 2.25%에서 2.50%로 인상했다. "
        "시장은 이를 사이클의 마지막 인상으로 본다.\n"
        "유로화는 강보합에 머물렀다."
    )
    matches = resolve_predictions(state, report)
    assert len(matches) == 2
    assert matches[0].matched is True
    assert matches[0].evidence
    assert "예금금리" in matches[0].matched_terms
    assert matches[1].matched is False
    assert matches[1].evidence == []


def test_resolve_predictions_skips_already_resolved() -> None:
    state = CurriculumState(
        predictions=[
            Prediction(made_in=1, question="ECB 인상?", resolution="적중"),
        ]
    )
    assert resolve_predictions(state, "ECB 인상이 있었다") == []


# --- 직렬화 ------------------------------------------------------------------


def test_state_json_roundtrip(tmp_path: Path) -> None:
    state = record_lecture(
        initial_state(),
        [
            SelectedTopic(
                id="ecb-policy-mechanics",
                title_ko=TOPIC_CATALOG["ecb-policy-mechanics"].title_ko,
                track="macro",
            )
        ],
        {"DFR": GlossaryEntry(lecture=1, definition_ko="예금금리")},
        [Prediction(question="9월 인상?", checkpoints=["2.50%"])],
    )
    path = tmp_path / "nested" / "curriculum_state.json"
    assert save_state(state, path) == path
    loaded = load_state(path)
    assert loaded.lecture_no == state.lecture_no
    assert loaded.covered_topics == state.covered_topics
    assert loaded.glossary == state.glossary
    assert loaded.predictions == state.predictions
    assert "한글" not in path.read_text(encoding="utf-8")  # ensure_ascii=False 확인
    assert "예금금리" in path.read_text(encoding="utf-8")


def test_load_state_returns_seed_when_missing(tmp_path: Path) -> None:
    state = load_state(tmp_path / "does-not-exist.json")
    assert state.lecture_no == 0
    assert state.topic_queue == list(INITIAL_TOPIC_QUEUE)


def test_load_state_reconciles_queue_with_catalog(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    stale = CurriculumState(
        lecture_no=3,
        covered_topics=[CoveredTopic(id="hicp-anatomy", lecture=1)],
        topic_queue=["ghost-topic", "ois-curve-reading"],
    )
    save_state(stale, path)
    loaded = load_state(path)
    assert "ghost-topic" not in loaded.topic_queue
    assert loaded.topic_queue[0] == "ois-curve-reading"
    assert "hicp-anatomy" not in loaded.topic_queue  # 이미 커버됨
    assert "sgp-fiscal-rules" in loaded.topic_queue  # 카탈로그 신규 주제 보충


@pytest.mark.parametrize("topic_id", sorted(TOPIC_CATALOG))
def test_catalog_entries_are_well_formed(topic_id: str) -> None:
    spec = TOPIC_CATALOG[topic_id]
    assert spec.id == topic_id
    assert spec.title_ko
    assert spec.track in {"macro", "politics"}
    assert len(spec.keywords) >= 3
