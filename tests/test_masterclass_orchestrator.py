"""Tests for the masterclass orchestrator (no live Claude CLI calls).

Every Claude CLI round-trip is mocked: either at ``_exec_claude`` (pipeline
behaviour) or at ``subprocess.Popen`` (CLI flag / stream-json contract).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from indepth_analysis.skills.euro_macro.masterclass import orchestrator as mc
from indepth_analysis.skills.euro_macro.masterclass.orchestrator import (
    CHAPTER_ORDER,
    PLACEHOLDER_MARK,
    MasterclassOrchestrator,
    assemble_lecture,
    curriculum_glossary,
    curriculum_predictions,
    curriculum_topics,
    extract_chapters,
    extract_json_block,
    extract_marker_block,
    format_issues,
    high_issues_from,
    parse_stream_json,
)

# ---------------------------------------------------------------------------
# Canned Claude CLI responses
# ---------------------------------------------------------------------------

TOPICS_RESPONSE = """\
===TOPICS_JSON_START===
{
  "lecture_no": 1,
  "topics": [
    {"id": "ecb-hiking-mechanics", "track": "macro", "chapter": 1,
     "title_ko": "ECB 인상 사이클의 해부", "depth": "core"},
    {"id": "hicp-anatomy", "track": "macro", "chapter": 2,
     "title_ko": "HICP의 내부", "depth": "intro"},
    {"id": "fr-institutions", "track": "politics", "chapter": 3,
     "title_ko": "프랑스 제도 역학", "depth": "intro"}
  ],
  "chapter_titles": {"1": "ECB 인상 사이클의 해부"}
}
===TOPICS_JSON_END===

===OUTLINE_START===
### 0장 이달의 지도
- 핵심 메시지
===OUTLINE_END===
"""

MACRO_RESPONSE = """\
===CHAPTER_0_START===
## 0장 이달의 지도
지도 본문입니다.
===CHAPTER_0_END===
===CHAPTER_1_START===
## 1장 ECB 인상 사이클의 해부
메커니즘 사슬 본문입니다.
===CHAPTER_1_END===
===CHAPTER_2_START===
## 2장 HICP의 내부
지표 해부 본문입니다.
===CHAPTER_2_END===
"""

POLITICS_RESPONSE = """\
===CHAPTER_3_START===
## 3장 프랑스 제도 역학
제도 본문입니다.
===CHAPTER_3_END===
===CHAPTER_4_START===
## 4장 숫자의 역사
| 월 | 값 |
|---|---|
| 2026-07 | 2.1 |
===CHAPTER_4_END===
"""

SYNTHESIS_RESPONSE = """\
===CHAPTER_5_START===
## 5장 전월과의 대화
델타 본문입니다.
===CHAPTER_5_END===
===CHAPTER_6_START===
## 6장 다음 달 시험 문제
체크포인트 본문입니다.
===CHAPTER_6_END===
===GLOSSARY_MD_START===
- **DFR** (Deposit Facility Rate): 예금금리입니다.
===GLOSSARY_MD_END===
===GLOSSARY_JSON_START===
```json
{"terms": [{"term": "DFR", "term_en": "Deposit Facility Rate",
            "definition_ko": "예금금리입니다.", "chapter": 1}]}
```
===GLOSSARY_JSON_END===
===PREDICTIONS_JSON_START===
{"predictions": [
  {"id": "ecb-sep", "question": "9월 ECB는 동결할까요?",
   "resolution_criteria": "9월 회의 DFR 발표", "resolve_after": "2026-09-30"}
]}
===PREDICTIONS_JSON_END===
"""

EVAL_CLEAN = '===ISSUES_JSON_START===\n{"issues": []}\n===ISSUES_JSON_END==='

EVAL_HIGH = """\
===ISSUES_JSON_START===
{"issues": [
  {"severity": "HIGH", "axis": "strawman", "chapter": 1,
   "quote": "반론은 설득력이 없습니다", "problem": "스트로맨",
   "fix": "가장 강한 반론으로 재작성"},
  {"severity": "MEDIUM", "axis": "length", "chapter": 2,
   "problem": "분량 부족", "fix": "보강"}
]}
===ISSUES_JSON_END===
"""

EVAL_MEDIUM_ONLY = """\
===ISSUES_JSON_START===
{"issues": [{"severity": "MEDIUM", "axis": "length", "chapter": 2,
             "problem": "분량 부족", "fix": "보강"}]}
===ISSUES_JSON_END===
"""

R2_RESPONSE = """\
===CHAPTER_1_START===
## 1장 ECB 인상 사이클의 해부
수정된 본문입니다. 반론을 가장 강한 형태로 재작성했습니다.
===CHAPTER_1_END===
"""


def _responder(evaluator: str = EVAL_CLEAN, calls: list[str] | None = None):
    """Build an ``_exec_claude`` replacement keyed on the call label."""
    table = {
        "topic_selection": TOPICS_RESPONSE,
        "write_macro": MACRO_RESPONSE,
        "write_politics_history": POLITICS_RESPONSE,
        "write_synthesis": SYNTHESIS_RESPONSE,
        "evaluator": evaluator,
        "revision_r2": R2_RESPONSE,
    }

    def _fake(self, user_prompt, system_prompt, timeout, label):  # noqa: ANN001
        if calls is not None:
            calls.append(label)
        return table[label]

    return _fake


@pytest.fixture
def orch(tmp_path: Path) -> MasterclassOrchestrator:
    return MasterclassOrchestrator(2026, 8, reports_dir=tmp_path / "reports")


# ---------------------------------------------------------------------------
# Marker parsing
# ---------------------------------------------------------------------------


def test_extract_marker_block_paired() -> None:
    body = extract_marker_block(TOPICS_RESPONSE, "OUTLINE")
    assert body.startswith("### 0장")
    assert "===" not in body


def test_extract_marker_block_bare_opener_fallback() -> None:
    text = "머리말\n===OUTLINE===\n본문 A\n===NEXT_THING===\n무시\n"
    assert extract_marker_block(text, "OUTLINE") == "본문 A"


def test_extract_marker_block_missing_returns_empty() -> None:
    assert extract_marker_block("아무 마커 없음", "TOPICS_JSON") == ""


def test_extract_topics_json() -> None:
    topics = extract_json_block(TOPICS_RESPONSE, "TOPICS_JSON")
    assert [t["id"] for t in topics["topics"]] == [
        "ecb-hiking-mechanics",
        "hicp-anatomy",
        "fr-institutions",
    ]
    assert topics["chapter_titles"]["1"] == "ECB 인상 사이클의 해부"


def test_extract_glossary_json_strips_code_fence() -> None:
    gloss = extract_json_block(SYNTHESIS_RESPONSE, "GLOSSARY_JSON")
    assert gloss["terms"][0]["term"] == "DFR"


def test_extract_predictions_json() -> None:
    preds = extract_json_block(SYNTHESIS_RESPONSE, "PREDICTIONS_JSON")
    assert preds["predictions"][0]["id"] == "ecb-sep"


def test_extract_issues_json_and_high_filter() -> None:
    payload = extract_json_block(EVAL_HIGH, "ISSUES_JSON")
    high = high_issues_from(payload)
    assert len(high) == 1
    assert high[0]["axis"] == "strawman"
    assert "스트로맨" in format_issues(high)


def test_extract_json_block_invalid_json_returns_none() -> None:
    bad = "===TOPICS_JSON_START===\nnot json at all\n===TOPICS_JSON_END==="
    assert extract_json_block(bad, "TOPICS_JSON") is None


def test_extract_json_block_tolerates_surrounding_prose() -> None:
    noisy = (
        "===ISSUES_JSON_START===\n결과입니다:\n"
        '{"issues": []}\n끝.\n===ISSUES_JSON_END==='
    )
    assert extract_json_block(noisy, "ISSUES_JSON") == {"issues": []}


def test_extract_chapters_restricted_to_expected() -> None:
    chapters = extract_chapters(MACRO_RESPONSE, (0, 1, 2))
    assert sorted(chapters) == [0, 1, 2]
    assert chapters[1].startswith("## 1장")
    assert extract_chapters(MACRO_RESPONSE, (5, 6)) == {}


def test_parse_stream_json_prefers_result_then_assistant() -> None:
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "부분"}]},
            }
        ),
        "garbage-not-json",
        json.dumps({"type": "result", "subtype": "success", "result": "최종"}),
    ]
    assert parse_stream_json("\n".join(lines)) == "최종"
    assert parse_stream_json(lines[0]) == "부분"


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def test_assemble_lecture_orders_chapters_and_appends_glossary() -> None:
    chapters = {n: f"## {n}장 제목\n본문 {n}" for n in CHAPTER_ORDER}
    md = assemble_lecture(
        chapters,
        lecture_no=3,
        year=2026,
        month=8,
        as_of="2026-08-31",
        topics={"topics": [{"title_ko": "주제 A"}]},
        glossary_md="- **DFR**: 예금금리",
    )
    assert md.startswith("# 유럽 매크로 마스터클래스 제3강 — 2026년 8월")
    assert "기준일(as-of): 2026-08-31" in md
    assert "이달의 주제: 주제 A" in md
    positions = [md.index(f"## {n}장") for n in CHAPTER_ORDER]
    assert positions == sorted(positions)
    assert md.index("부록 — 용어사전 증분") > positions[-1]


def test_assemble_lecture_inserts_placeholder_for_missing_chapter() -> None:
    md = assemble_lecture(
        {0: "## 0장 지도\n본문"},
        lecture_no=1,
        year=2026,
        month=8,
        as_of="2026-08-31",
    )
    assert md.count(PLACEHOLDER_MARK) == len(CHAPTER_ORDER) - 1
    assert "## 6장" in md


# ---------------------------------------------------------------------------
# Stage 3 — parallel writing / placeholders
# ---------------------------------------------------------------------------


def test_write_all_marks_failed_writer_chapters_as_placeholder(
    orch: MasterclassOrchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake(self, user_prompt, system_prompt, timeout, label):  # noqa: ANN001
        if label == "write_politics_history":
            raise RuntimeError("boom")
        return {
            "write_macro": MACRO_RESPONSE,
            "write_synthesis": SYNTHESIS_RESPONSE,
        }[label]

    monkeypatch.setattr(MasterclassOrchestrator, "_exec_claude", _fake)
    kwargs = {"dummy": "x"}
    monkeypatch.setattr(
        mc, "WRITE_MACRO_PROMPT", "macro", raising=True
    )
    monkeypatch.setattr(mc, "WRITE_POLITICS_HISTORY_PROMPT", "pol")
    monkeypatch.setattr(mc, "WRITE_SYNTHESIS_PROMPT", "syn")

    chapters, extras, status = asyncio.run(orch._write_all(kwargs))

    assert status[3] == "placeholder"
    assert status[4] == "placeholder"
    assert PLACEHOLDER_MARK in chapters[3]
    assert "boom" in chapters[4]
    assert status[0] == status[1] == status[2] == "ok"
    assert status[5] == status[6] == "ok"
    assert extras["predictions"][0]["id"] == "ecb-sep"
    assert extras["glossary"]["terms"][0]["term"] == "DFR"
    assert any("실패" in w for w in orch.warnings)


def test_write_all_missing_marker_block_becomes_placeholder(
    orch: MasterclassOrchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    truncated = MACRO_RESPONSE.split("===CHAPTER_2_START===")[0]

    def _fake(self, user_prompt, system_prompt, timeout, label):  # noqa: ANN001
        return {
            "write_macro": truncated,
            "write_politics_history": POLITICS_RESPONSE,
            "write_synthesis": SYNTHESIS_RESPONSE,
        }[label]

    monkeypatch.setattr(MasterclassOrchestrator, "_exec_claude", _fake)
    monkeypatch.setattr(mc, "WRITE_MACRO_PROMPT", "macro")
    monkeypatch.setattr(mc, "WRITE_POLITICS_HISTORY_PROMPT", "pol")
    monkeypatch.setattr(mc, "WRITE_SYNTHESIS_PROMPT", "syn")

    chapters, _extras, status = asyncio.run(orch._write_all({}))
    assert status[2] == "placeholder"
    assert "마커 블록 누락" in chapters[2]
    assert status[0] == "ok"


# ---------------------------------------------------------------------------
# Claude CLI contract
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self._stdout = stdout
        self.returncode = returncode

    def communicate(self, timeout: int | None = None):  # noqa: ANN001
        return self._stdout, ""

    def kill(self) -> None:  # pragma: no cover - not exercised
        pass


def test_exec_claude_uses_house_cli_flags(
    orch: MasterclassOrchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    stream = json.dumps(
        {"type": "result", "subtype": "success", "result": "본문"}
    )

    def _popen(cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = cmd
        return _FakeProc(stream)

    monkeypatch.setattr(mc.subprocess, "Popen", _popen)
    out = orch._exec_claude("user", "system", 10, "evaluator")

    assert out == "본문"
    cmd = captured["cmd"]
    assert cmd[0] == "claude"
    assert "--output-format" in cmd and "stream-json" in cmd
    assert "--verbose" in cmd
    assert "--append-system-prompt" in cmd
    # Writing/evaluation calls are pure generation — no tools.
    assert "--allowedTools" not in cmd
    assert "<system>" not in " ".join(cmd)


def test_call_claude_retries_once_then_raises(
    orch: MasterclassOrchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[str] = []

    def _fake(self, user_prompt, system_prompt, timeout, label):  # noqa: ANN001
        attempts.append(label)
        raise RuntimeError("cli down")

    monkeypatch.setattr(MasterclassOrchestrator, "_exec_claude", _fake)
    with pytest.raises(RuntimeError):
        orch._call_claude("u", "s", 5, "evaluator")
    assert len(attempts) == 2  # 1 try + 1 retry


def test_call_claude_retry_recovers(
    orch: MasterclassOrchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"n": 0}

    def _fake(self, user_prompt, system_prompt, timeout, label):  # noqa: ANN001
        state["n"] += 1
        if state["n"] == 1:
            return ""  # empty output triggers the retry
        return "ok"

    monkeypatch.setattr(MasterclassOrchestrator, "_exec_claude", _fake)
    assert orch._call_claude("u", "s", 5, "evaluator") == "ok"


# ---------------------------------------------------------------------------
# Stage 4 — evaluator / R2 trigger
# ---------------------------------------------------------------------------


def test_r2_triggered_only_on_high_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        MasterclassOrchestrator,
        "_exec_claude",
        _responder(EVAL_HIGH, calls),
    )
    orch = MasterclassOrchestrator(2026, 8, reports_dir=tmp_path / "r")
    result = orch.run()

    assert "revision_r2" in calls
    assert result.revised is True
    assert result.chapter_status[1] == "revised"
    assert "수정된 본문" in result.markdown
    assert len(result.high_issues) == 1
    assert len(result.medium_issues) == 1


def test_no_r2_when_only_medium_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        MasterclassOrchestrator,
        "_exec_claude",
        _responder(EVAL_MEDIUM_ONLY, calls),
    )
    result = MasterclassOrchestrator(2026, 8, reports_dir=tmp_path / "r").run()

    assert "revision_r2" not in calls
    assert result.revised is False
    assert result.medium_issues and not result.high_issues


def test_skip_evaluator_skips_stage_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        MasterclassOrchestrator, "_exec_claude", _responder(EVAL_HIGH, calls)
    )
    orch = MasterclassOrchestrator(
        2026, 8, reports_dir=tmp_path / "r", skip_evaluator=True
    )
    result = orch.run()
    assert "evaluator" not in calls
    assert "revision_r2" not in calls
    assert result.high_issues == []


# ---------------------------------------------------------------------------
# Stage 5 — gates are advisory
# ---------------------------------------------------------------------------


def test_gates_are_advisory_and_do_not_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import indepth_analysis.temporal_lint as tl

    class _Finding:
        line_no = 3
        severity = "high"
        text = "2025년 합의가 이번 달 발효됩니다"

    monkeypatch.setattr(
        tl, "scan_temporal_issues", lambda text, year, **kw: [_Finding()]
    )
    monkeypatch.setattr(
        MasterclassOrchestrator, "_exec_claude", _responder()
    )
    result = MasterclassOrchestrator(2026, 8, reports_dir=tmp_path / "r").run()

    assert result.gate_findings["temporal"], "advisory finding should surface"
    assert result.report_path.exists(), "gate must not block the save"


def test_gate_failure_is_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import indepth_analysis.temporal_lint as tl

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("lint exploded")

    monkeypatch.setattr(tl, "scan_temporal_issues", _boom)
    monkeypatch.setattr(MasterclassOrchestrator, "_exec_claude", _responder())
    result = MasterclassOrchestrator(2026, 8, reports_dir=tmp_path / "r").run()
    assert result.gate_findings["temporal"] == []
    assert result.report_path.exists()


# ---------------------------------------------------------------------------
# Full run + curriculum side effects
# ---------------------------------------------------------------------------


def test_run_saves_lecture_and_updates_curriculum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(MasterclassOrchestrator, "_exec_claude", _responder())
    reports = tmp_path / "reports"
    orch = MasterclassOrchestrator(2026, 8, reports_dir=reports)
    result = orch.run()

    expected = reports / "euro_macro" / "masterclass" / "2026-08-masterclass.md"
    assert result.report_path == expected
    assert expected.exists()

    md = expected.read_text(encoding="utf-8")
    assert md.startswith("# 유럽 매크로 마스터클래스 제1강 — 2026년 8월")
    assert result.lecture_no == 1
    assert PLACEHOLDER_MARK not in md
    assert all(status == "ok" for status in result.chapter_status.values())

    state_file = reports / "euro_macro" / "masterclass" / "curriculum_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state["lecture_no"] == 1
    assert {t["id"] for t in state["covered_topics"]} >= {"hicp-anatomy"}
    assert state["glossary"]["DFR"]["definition_ko"].startswith("예금금리")
    assert state["predictions"][0]["made_in"] == 1


def test_run_degrades_when_topic_selection_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _responder()

    def _fake(self, user_prompt, system_prompt, timeout, label):  # noqa: ANN001
        if label == "topic_selection":
            raise RuntimeError("no topics")
        return base(self, user_prompt, system_prompt, timeout, label)

    monkeypatch.setattr(MasterclassOrchestrator, "_exec_claude", _fake)
    result = MasterclassOrchestrator(2026, 8, reports_dir=tmp_path / "r").run()

    assert result.topics.get("fallback") is True
    assert result.report_path.exists()
    assert any("주제 선정" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Context-pack slot rendering
# ---------------------------------------------------------------------------


def test_prompt_slots_render_from_context_pack_shape(tmp_path: Path) -> None:
    pack = {
        "report_title": "2026년 8월 유럽 거시경제",
        "sections": [
            {
                "key": "1",
                "heading": "1. ECB 통화정책",
                "kind": "body",
                "text": "ECB는 DFR을 2.25%로 유지했습니다. " * 40,
                "subheadings": ["1.1 결정"],
            },
            {
                "key": "A",
                "heading": "A. 향후 14일 캘린더",
                "kind": "deterministic",
                "text": "| 날짜 | 이벤트 |\n|---|---|\n| 09-11 | ECB |",
            },
        ],
        "headline_numbers": ["DFR 2.25% 유지"],
        "backbone_tables": [
            {
                "id": "hicp",
                "title": "HICP 체인",
                "rows": [{"m": "2026-07"}],
                "markdown": "| 월 | 값 |\n|---|---|\n| 2026-07 | 2.1 |",
                "source": "macro store",
            }
        ],
        "deltas": [
            {
                "key": "1",
                "curr_heading": "1. ECB 통화정책",
                "prev_gist": "전월 요지",
                "curr_gist": "당월 요지",
                "curr_numbers": ["2.25%"],
            }
        ],
    }
    orch = MasterclassOrchestrator(2026, 8, reports_dir=tmp_path / "r")
    slots = orch._build_prompt_kwargs(pack, {}, {}, 1, "2026-08-31")

    assert "1. ECB 통화정책" in slots["report_digest"]
    assert "DFR 2.25% 유지" in slots["factsheet"]
    assert "| 2026-07 | 2.1 |" in slots["history_tables"]
    assert "전월 요지" in slots["prev_delta"]
    assert "ECB" in slots["calendar"]
    assert slots["as_of"] == "2026-08-31"

    # Every writer template must format cleanly against this one dict.
    for template in (
        mc.WRITE_MACRO_PROMPT,
        mc.WRITE_POLITICS_HISTORY_PROMPT,
        mc.WRITE_SYNTHESIS_PROMPT,
        mc.TOPIC_SELECTION_PROMPT,
        mc.EVALUATOR_PROMPT,
        mc.REVISION_PROMPT,
    ):
        assert template.format(**slots)


def test_pre_rendered_pack_keys_win_over_renderers(tmp_path: Path) -> None:
    orch = MasterclassOrchestrator(2026, 8, reports_dir=tmp_path / "r")
    slots = orch._build_prompt_kwargs(
        {"factsheet": "직접 주입한 팩트시트", "sections": []},
        {},
        {},
        2,
        "2026-08-31",
    )
    assert slots["factsheet"] == "직접 주입한 팩트시트"


# ---------------------------------------------------------------------------
# Curriculum payload normalisation
# ---------------------------------------------------------------------------


def test_curriculum_topics_normalises_track_and_depth() -> None:
    rows = curriculum_topics(
        [
            {"id": "a", "track": "MACRO", "depth": "advanced", "title_ko": "A"},
            {"id": "b", "track": "geopolitics", "depth": "deep"},
            {"no_id": True},
            "not-a-dict",
        ]
    )
    assert [r["id"] for r in rows] == ["a", "b"]
    assert rows[0]["track"] == "macro"
    assert rows[0]["depth"] == "advanced"
    assert rows[1]["track"] == "macro"  # unknown track falls back
    assert rows[1]["depth"] == "intro"  # unknown depth falls back
    assert rows[1]["title_ko"] == "b"


def test_curriculum_glossary_and_predictions_shapes() -> None:
    gloss = curriculum_glossary(
        {"terms": [{"term": "DFR", "definition_ko": "예금금리"}]}
    )
    assert gloss == {"DFR": "예금금리"}
    assert curriculum_glossary({"OIS": "오버나이트"}) == {"OIS": "오버나이트"}

    preds = curriculum_predictions(
        {
            "predictions": [
                {"question": "Q1?", "resolution_criteria": "9월 발표"},
                {"question": "", "resolution_criteria": "무시"},
            ]
        }
    )
    assert preds == [
        {"question": "Q1?", "checkpoints": ["9월 발표"], "resolution": None}
    ]
