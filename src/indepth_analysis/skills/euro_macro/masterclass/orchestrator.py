"""Masterclass orchestrator — context pack → topics → 3 parallel writers →
evaluator (+R2) → advisory gates → save → curriculum update.

Follows the weekly_brief conventions for Claude CLI subprocess execution and
``===MARKER===`` block parsing, rewritten for the 7-chapter lecture format.

Hard constraints (CLAUDE.md):
  * Anthropic SDK is forbidden — Claude is only invoked via the ``claude`` CLI.
  * No ``<system>`` tags in prompts; system text goes to
    ``--append-system-prompt``.
  * ``--output-format stream-json`` always paired with ``--verbose``.
  * Writing/synthesis calls get no extra tools.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from bgilib.obs import CallKind, span
from bgilib.obs.extractors.claude_cli import parse_stream_json_text

from indepth_analysis.skills.euro_macro.masterclass.prompts import (
    EVALUATOR_PROMPT,
    EVALUATOR_SYSTEM_PROMPT,
    REVISION_PROMPT,
    REVISION_SYSTEM_PROMPT,
    TOPIC_SELECTION_PROMPT,
    TOPIC_SELECTION_SYSTEM_PROMPT,
    WRITE_MACRO_PROMPT,
    WRITE_POLITICS_HISTORY_PROMPT,
    WRITE_SYNTHESIS_PROMPT,
    WRITER_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"

#: Chapter number → default title (Stage 2 may override via chapter_titles).
CHAPTER_TITLES: dict[int, str] = {
    0: "이달의 지도",
    1: "사건 심화 I — 매크로",
    2: "사건 심화 II — 지표·시장",
    3: "정치·제도 심화",
    4: "숫자의 역사",
    5: "전월과의 대화",
    6: "다음 달 시험 문제",
}

#: Writer call → chapters it owns.
WRITER_CHAPTERS: dict[str, tuple[int, ...]] = {
    "macro": (0, 1, 2),
    "politics_history": (3, 4),
    "synthesis": (5, 6),
}

CHAPTER_ORDER: tuple[int, ...] = tuple(sorted(CHAPTER_TITLES))

PLACEHOLDER_MARK = "[자동 생성 실패]"


# ---------------------------------------------------------------------------
# Marker parsing helpers (module level — unit-testable without an orchestrator)
# ---------------------------------------------------------------------------


def extract_marker_block(text: str, name: str) -> str:
    """Return the body of a ``===NAME_START===`` … ``===NAME_END===`` block.

    Falls back to a bare ``===NAME===`` opener, in which case the block runs
    until the next ``===...===`` marker line or the end of the text. Returns
    ``""`` when the marker is absent.
    """
    if not text:
        return ""

    paired = re.compile(
        rf"^===\s*{re.escape(name)}_START\s*===\s*$(.*?)^===\s*{re.escape(name)}"
        r"_END\s*===\s*$",
        re.DOTALL | re.MULTILINE,
    )
    m = paired.search(text)
    if m:
        return m.group(1).strip()

    bare = re.compile(
        rf"^===\s*{re.escape(name)}\s*===\s*$(.*?)(?=^===[^\n]*===\s*$|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    m = bare.search(text)
    if m:
        return m.group(1).strip()
    return ""


def _strip_code_fence(raw: str) -> str:
    """Remove a surrounding ```json … ``` fence if the model added one."""
    m = re.match(r"```(?:json)?\s*(.*?)\s*```\s*$", raw.strip(), re.DOTALL)
    return m.group(1).strip() if m else raw.strip()


def extract_json_block(text: str, name: str) -> Any:
    """Extract a marker block and parse it as JSON. ``None`` on any failure."""
    body = _strip_code_fence(extract_marker_block(text, name))
    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        # Tolerate leading/trailing prose around the JSON object.
        start = body.find("{")
        end = body.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(body[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                pass
        logger.warning("masterclass: %s block is not valid JSON", name)
        return None


def extract_chapters(
    text: str, expected: tuple[int, ...] | None = None
) -> dict[int, str]:
    """Pull ``===CHAPTER_N_START===`` blocks out of a writer response.

    ``expected`` restricts the search; when omitted every chapter number in
    :data:`CHAPTER_ORDER` is attempted.
    """
    numbers = expected if expected is not None else CHAPTER_ORDER
    out: dict[int, str] = {}
    for n in numbers:
        body = extract_marker_block(text, f"CHAPTER_{n}")
        if body:
            out[n] = body
    return out


def chapter_placeholder(n: int, title: str, reason: str) -> str:
    """Markdown stand-in for a chapter whose generation failed."""
    return (
        f"## {n}장 {title}\n\n"
        f"> **{PLACEHOLDER_MARK}** 이 장은 생성 파이프라인 오류로 비어 있습니다 "
        f"(원인: {reason}). 다음 실행에서 재생성이 필요합니다.\n"
    )


def assemble_lecture(
    chapters: dict[int, str],
    *,
    lecture_no: int,
    year: int,
    month: int,
    as_of: str,
    topics: dict[str, Any] | None = None,
    glossary_md: str = "",
) -> str:
    """Join chapters in canonical order under the lecture header."""
    titles = dict(CHAPTER_TITLES)
    if topics:
        raw_titles = topics.get("chapter_titles") or {}
        if isinstance(raw_titles, dict):
            for key, value in raw_titles.items():
                try:
                    titles[int(key)] = str(value)
                except (TypeError, ValueError):
                    continue

    parts: list[str] = [
        f"# 유럽 매크로 마스터클래스 제{lecture_no}강 — {year}년 {month}월",
        "",
        f"> 기준일(as-of): {as_of}  |  회차: 제{lecture_no}강",
    ]

    topic_titles = _topic_titles(topics)
    if topic_titles:
        parts.append("> 이달의 주제: " + " / ".join(topic_titles))
    parts.append("")

    for n in CHAPTER_ORDER:
        body = (chapters.get(n) or "").strip()
        if not body:
            body = chapter_placeholder(n, titles.get(n, ""), "본문 누락")
        if not body.lstrip().startswith("#"):
            body = f"## {n}장 {titles.get(n, '')}\n\n{body}"
        parts.append(body)
        parts.append("")

    if glossary_md.strip():
        gloss = glossary_md.strip()
        if not gloss.lstrip().startswith("#"):
            gloss = f"## 부록 — 용어사전 증분 (제{lecture_no}강 신규)\n\n{gloss}"
        parts.append(gloss)
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _topic_titles(topics: dict[str, Any] | None) -> list[str]:
    if not topics:
        return []
    items = topics.get("topics")
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            title = item.get("title_ko") or item.get("id")
            if title:
                out.append(str(title))
    return out


def high_issues_from(issues: Any) -> list[dict[str, Any]]:
    """Normalise an evaluator payload into the list of HIGH issues."""
    if isinstance(issues, dict):
        items = issues.get("issues")
    else:
        items = issues
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("severity", "")).strip().upper() == "HIGH"
    ]


def _gist_text(text: str, limit: int = 700) -> str:
    """First ``limit`` chars of a section, cut on a sentence boundary."""
    body = " ".join(
        line.strip()
        for line in (text or "").splitlines()
        if line.strip() and not line.strip().startswith(("|", "#", ">", "---"))
    )
    if len(body) <= limit:
        return body
    cut = body[:limit]
    for sep in ("다. ", ". ", " "):
        idx = cut.rfind(sep)
        if idx > limit // 2:
            return cut[: idx + len(sep)].strip() + " …"
    return cut + " …"


def render_report_digest(pack: dict[str, Any]) -> str:
    """Section-by-section gist of the month's report (Stage 2/3 input)."""
    lines: list[str] = []
    title = pack.get("report_title")
    if title:
        lines.append(f"# {title}")
    for sec in pack.get("sections") or []:
        if not isinstance(sec, dict) or sec.get("kind") == "meta":
            continue
        heading = sec.get("heading") or sec.get("key") or ""
        lines.append(f"\n### [{sec.get('kind', '')}] {heading}")
        gist = _gist_text(str(sec.get("text") or ""))
        if gist:
            lines.append(gist)
        subs = [str(s) for s in (sec.get("subheadings") or [])][:12]
        if subs:
            lines.append("소제목: " + " / ".join(subs))
    return "\n".join(lines).strip()


def render_report_text(pack: dict[str, Any]) -> str:
    """Full section text of the month's report (prediction matching input)."""
    return "\n\n".join(
        str(sec.get("text") or "")
        for sec in pack.get("sections") or []
        if isinstance(sec, dict)
    ).strip()


def render_factsheet(pack: dict[str, Any]) -> str:
    """The only numbers the writer may use in prose."""
    lines = ["## 이달 리포트 핵심 수치 문장 (산문에 쓸 수 있는 유일한 수치 출처)"]
    numbers = [str(s) for s in (pack.get("headline_numbers") or [])]
    lines += [f"- {s}" for s in numbers] or ["- (수치 문장 없음)"]

    tables = [t for t in (pack.get("backbone_tables") or []) if isinstance(t, dict)]
    if tables:
        lines.append("")
        lines.append("## 코드 생성 표 (4장에 원문 그대로 삽입 — 재작성 금지)")
        for tbl in tables:
            rows = tbl.get("rows") or []
            lines.append(
                f"- {tbl.get('title', tbl.get('id', ''))} "
                f"({len(rows)}행, 출처: {tbl.get('source', 'n/a')})"
            )

    sources = [str(s) for s in (pack.get("inline_sources") or [])][:40]
    if sources:
        lines.append("")
        lines.append("## 리포트 인라인 출처")
        lines += [f"- {s}" for s in sources]
    return "\n".join(lines)


def render_history_tables(pack: dict[str, Any]) -> str:
    """Chapter 4 tables — inserted verbatim, never regenerated by the LLM."""
    blocks: list[str] = []
    for tbl in pack.get("backbone_tables") or []:
        if not isinstance(tbl, dict):
            continue
        head = f"### {tbl.get('title', tbl.get('id', ''))}"
        markdown = str(tbl.get("markdown") or "").strip()
        if not markdown or not (tbl.get("rows") or []):
            note = tbl.get("note") or "데이터 없음"
            blocks.append(f"{head}\n\n(표 생성 불가 — {note})")
            continue
        tail = []
        if tbl.get("source"):
            tail.append(f"출처: {tbl['source']}")
        if tbl.get("note"):
            tail.append(f"비고: {tbl['note']}")
        blocks.append(
            head + "\n\n" + markdown + ("\n\n" + " / ".join(tail) if tail else "")
        )
    return "\n\n".join(blocks)


def render_prev_delta(pack: dict[str, Any]) -> str:
    """Month-over-month section deltas (chapter 5 raw material)."""
    blocks: list[str] = []
    for delta in pack.get("deltas") or []:
        if not isinstance(delta, dict):
            continue
        head = (
            f"### {delta.get('curr_heading') or delta.get('key', '')} "
            f"(match={delta.get('match_kind', '')})"
        )
        prev_nums = [str(n) for n in (delta.get("prev_numbers") or [])][:6]
        curr_nums = [str(n) for n in (delta.get("curr_numbers") or [])][:6]
        blocks.append(
            "\n".join(
                [
                    head,
                    f"- 전월: {delta.get('prev_gist') or '(없음)'}",
                    f"- 당월: {delta.get('curr_gist') or '(없음)'}",
                    f"- 전월 수치: {' | '.join(prev_nums) or '(없음)'}",
                    f"- 당월 수치: {' | '.join(curr_nums) or '(없음)'}",
                ]
            )
        )
    return "\n\n".join(blocks)


def render_calendar(pack: dict[str, Any]) -> str:
    """Forward calendar text from the report's deterministic sections."""
    for sec in pack.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading") or "")
        if "캘린더" in heading or "일정" in heading:
            return str(sec.get("text") or "")[:4000]
    return ""


def curriculum_topics(items: list[Any]) -> list[dict[str, Any]]:
    """Normalise Stage 2 topic dicts into ``SelectedTopic``-shaped rows."""
    valid_tracks = ("macro", "politics")
    valid_depth = ("intro", "core", "advanced")
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        topic_id = str(item.get("id") or item.get("topic_id") or "").strip()
        if not topic_id:
            continue
        track = str(item.get("track") or "macro").strip().lower()
        depth = str(item.get("depth") or "intro").strip().lower()
        rows.append(
            {
                "id": topic_id,
                "title_ko": str(item.get("title_ko") or topic_id),
                "track": track if track in valid_tracks else "macro",
                "depth": depth if depth in valid_depth else "intro",
                "reason": str(item.get("rationale") or item.get("reason") or ""),
            }
        )
    return rows


def curriculum_glossary(glossary: Any) -> dict[str, str]:
    """``{"terms": [{term, definition_ko}]}`` → ``{term: definition_ko}``."""
    if isinstance(glossary, dict):
        terms = glossary.get("terms", glossary)
    else:
        terms = glossary
    out: dict[str, str] = {}
    if isinstance(terms, dict):
        for key, value in terms.items():
            if isinstance(value, str):
                out[str(key)] = value
            elif isinstance(value, dict):
                out[str(key)] = str(value.get("definition_ko") or "")
        return out
    if isinstance(terms, list):
        for item in terms:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term") or "").strip()
            if term:
                out[term] = str(item.get("definition_ko") or "")
    return out


def curriculum_predictions(predictions: Any) -> list[dict[str, Any]]:
    """Normalise Stage 3 prediction dicts into ``Prediction``-shaped rows."""
    if isinstance(predictions, dict):
        predictions = predictions.get("predictions")
    if not isinstance(predictions, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in predictions:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        checkpoints = item.get("checkpoints")
        if not isinstance(checkpoints, list):
            criteria = item.get("resolution_criteria")
            checkpoints = [str(criteria)] if criteria else []
        rows.append(
            {
                "question": question,
                "checkpoints": [str(c) for c in checkpoints if str(c).strip()],
                "resolution": None,
            }
        )
    return rows


def format_issues(items: list[dict[str, Any]]) -> str:
    """Render issue dicts as a markdown list for the revision prompt."""
    lines: list[str] = []
    for item in items:
        chapter = item.get("chapter")
        axis = item.get("axis", "")
        head = f"- [{axis}] {chapter}장" if chapter is not None else f"- [{axis}]"
        lines.append(head)
        if item.get("quote"):
            lines.append(f"  - 원문: {item['quote']}")
        if item.get("problem"):
            lines.append(f"  - 문제: {item['problem']}")
        if item.get("fix"):
            lines.append(f"  - 수정: {item['fix']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class MasterclassResult:
    """Output of a full masterclass pipeline run."""

    year: int
    month: int
    lecture_no: int
    as_of: str
    report_path: Path
    markdown: str = ""
    topics: dict[str, Any] = field(default_factory=dict)
    outline: str = ""
    glossary: dict[str, Any] = field(default_factory=dict)
    predictions: list[dict[str, Any]] = field(default_factory=list)
    chapter_status: dict[int, str] = field(default_factory=dict)
    high_issues: list[dict[str, Any]] = field(default_factory=list)
    medium_issues: list[dict[str, Any]] = field(default_factory=list)
    revised: bool = False
    gate_findings: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    model_used: str = ""
    generated_at: str = ""
    char_count: int = 0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class MasterclassOrchestrator:
    """Run the masterclass pipeline for one month."""

    TOPIC_TIMEOUT = 300
    WRITE_TIMEOUT = 600
    EVALUATOR_TIMEOUT = 300
    REVISION_TIMEOUT = 600
    MAX_PARALLEL_WRITERS = 3

    def __init__(
        self,
        year: int,
        month: int,
        *,
        model: str = DEFAULT_MODEL,
        reports_dir: Path | str = Path("reports"),
        skip_evaluator: bool = False,
    ) -> None:
        self.year = year
        self.month = month
        self.model = model
        self.reports_dir = Path(reports_dir)
        self.skip_evaluator = skip_evaluator
        self.out_dir = self.reports_dir / "euro_macro" / "masterclass"
        self.warnings: list[str] = []

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @property
    def stem(self) -> str:
        return f"{self.year}-{self.month:02d}"

    @property
    def context_path(self) -> Path:
        return self.out_dir / f"{self.stem}-context.json"

    @property
    def state_path(self) -> Path:
        return self.out_dir / "curriculum_state.json"

    @property
    def lecture_path(self) -> Path:
        return self.out_dir / f"{self.stem}-masterclass.md"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> MasterclassResult:
        """Full pipeline. Never aborts on a single failed stage."""
        logger.info(
            "Masterclass: start (%s, model=%s)", self.stem, self.model
        )
        pack = self._load_context_pack()
        state_obj = self._load_curriculum()
        state = _as_dict(state_obj)
        lecture_no = self._next_lecture_no(state)
        as_of = str(pack.get("as_of") or self._default_as_of())

        prompt_kwargs = self._build_prompt_kwargs(
            pack, state, state_obj, lecture_no, as_of
        )

        # Stage 2 — topic selection.
        topics, outline = self._select_topics(prompt_kwargs)
        prompt_kwargs["topics_json"] = json.dumps(
            topics, ensure_ascii=False, indent=2
        )
        prompt_kwargs["outline"] = outline or "(아웃라인 미생성 — 자유 구성)"

        # Stage 3 — parallel writing.
        chapters, extras, status = asyncio.run(self._write_all(prompt_kwargs))

        glossary = extras.get("glossary") or {}
        predictions = extras.get("predictions") or []
        glossary_md = extras.get("glossary_md", "")

        markdown = assemble_lecture(
            chapters,
            lecture_no=lecture_no,
            year=self.year,
            month=self.month,
            as_of=as_of,
            topics=topics,
            glossary_md=glossary_md,
        )

        # Stage 4 — evaluator (+ single revision round).
        high: list[dict[str, Any]] = []
        medium: list[dict[str, Any]] = []
        revised = False
        if not self.skip_evaluator:
            high, medium = self._evaluate(markdown, prompt_kwargs)
            if high:
                revised_md = self._revise(
                    markdown, high, chapters, prompt_kwargs, glossary_md,
                    lecture_no, as_of, topics, status,
                )
                if revised_md:
                    markdown = revised_md
                    revised = True

        # Stage 5 — advisory gates (never block).
        gate_findings = self._run_gates(markdown)

        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.lecture_path.write_text(markdown, encoding="utf-8")
        logger.info(
            "Masterclass: saved %s (%d chars)", self.lecture_path, len(markdown)
        )

        self._record_curriculum(
            state_obj,
            topics=topics,
            glossary=glossary,
            predictions=predictions,
        )

        return MasterclassResult(
            year=self.year,
            month=self.month,
            lecture_no=lecture_no,
            as_of=as_of,
            report_path=self.lecture_path,
            markdown=markdown,
            topics=topics,
            outline=outline,
            glossary=glossary,
            predictions=predictions,
            chapter_status=status,
            high_issues=high,
            medium_issues=medium,
            revised=revised,
            gate_findings=gate_findings,
            warnings=list(self.warnings),
            model_used=self.model,
            generated_at=datetime.now(UTC).isoformat(),
            char_count=len(markdown),
        )

    # ------------------------------------------------------------------
    # Stage 1 inputs — context pack + curriculum (TE1-owned modules)
    # ------------------------------------------------------------------

    def _default_as_of(self) -> str:
        """Month-end anchor for the lecture's as-of date."""
        return self._month_end().isoformat()

    def _month_end(self) -> date:
        last = calendar.monthrange(self.year, self.month)[1]
        return date(self.year, self.month, last)

    def _prev_lecture_digest(self, limit: int = 4000) -> str:
        """Head of last month's lecture (chapter 5 continuity + 예측 채점)."""
        prev_y, prev_m = (
            (self.year - 1, 12) if self.month == 1 else (self.year, self.month - 1)
        )
        path = self.out_dir / f"{prev_y}-{prev_m:02d}-masterclass.md"
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("prev lecture unreadable: %s", exc)
            return ""
        return text[:limit] + (" …" if len(text) > limit else "")

    def _load_context_pack(self) -> dict[str, Any]:
        """Load ``{Y}-{MM}-context.json``; build (and save) it when missing."""
        if self.context_path.exists():
            try:
                data = json.loads(self.context_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError) as exc:
                self._warn(f"context pack 로드 실패 ({exc}) — 재생성 시도")

        try:
            from indepth_analysis.skills.euro_macro.masterclass import (
                context_pack as cp,
            )

            pack = cp.build_context_pack(
                self.year, self.month, reports_dir=self.reports_dir / "euro_macro"
            )
            try:
                cp.save_context_pack(pack, self.context_path)
            except Exception as exc:  # noqa: BLE001 — saving is best-effort
                logger.warning("context pack 저장 실패: %s", exc)
            return _as_dict(pack)
        except Exception as exc:  # noqa: BLE001 — degrade, never abort
            self._warn(f"context pack 생성 실패 ({exc}) — 빈 팩으로 진행")
            return {}

    def _load_curriculum(self) -> Any:
        """Load the cumulative curriculum state object (TE1 pydantic model).

        Returns the module's own state object when available so that
        ``record_lecture``/``save_state`` can round-trip it; falls back to a
        plain dict when the module is missing.
        """
        mod = self._curriculum_module()
        if mod is None:
            return _fallback_state()
        try:
            return _try_variants(
                mod.load_state, [((self.state_path,), {}), ((), {})]
            )
        except Exception as exc:  # noqa: BLE001
            self._warn(f"커리큘럼 상태 로드 실패 ({exc}) — 초기 상태 사용")
            initial = getattr(mod, "initial_state", None)
            if callable(initial):
                try:
                    return initial()
                except Exception:  # noqa: BLE001
                    pass
            return _fallback_state()

    @staticmethod
    def _curriculum_module() -> Any:
        try:
            from indepth_analysis.skills.euro_macro.masterclass import (
                curriculum,
            )

            return curriculum
        except Exception as exc:  # noqa: BLE001
            logger.warning("masterclass: curriculum module unavailable: %s", exc)
            return None

    def _next_lecture_no(self, state: dict[str, Any]) -> int:
        mod = self._curriculum_module()
        fn = getattr(mod, "next_lecture_no", None) if mod else None
        if callable(fn):
            try:
                return int(fn(state))
            except Exception:  # noqa: BLE001
                pass
        try:
            return int(state.get("lecture_no") or 0) + 1
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _raw_candidates(pack: dict[str, Any]) -> list[dict[str, Any]]:
        """Topic candidates as produced by the context pack (key-tolerant)."""
        for key in ("topic_candidates", "candidates", "topic_suggestions"):
            value = pack.get(key)
            if isinstance(value, list) and value:
                return [item for item in value if isinstance(item, dict)]
        return []

    def _topic_candidates(self, state_obj: Any, pack: dict[str, Any]) -> str:
        """Deterministic curriculum suggestions; degrades to the raw queue."""
        mod = self._curriculum_module()
        raw = self._raw_candidates(pack)
        fn = getattr(mod, "select_topics", None) if mod else None
        candidate_model = getattr(mod, "TopicCandidate", None) if mod else None
        if callable(fn) and raw and candidate_model is not None:
            try:
                cands = [candidate_model.model_validate(item) for item in raw]
                return _stringify(_as_dict(fn(state_obj, cands)))
            except Exception as exc:  # noqa: BLE001
                logger.debug("select_topics unavailable: %s", exc)
        return _stringify(pack.get("topic_suggestions") or raw)

    def _prev_predictions(self, state_obj: Any, pack: dict[str, Any]) -> str:
        """Prior-lecture predictions plus (if available) grading evidence."""
        state = _as_dict(state_obj)
        pending = state.get("predictions") or []
        mod = self._curriculum_module()
        fn = getattr(mod, "resolve_predictions", None) if mod else None
        report_text = _stringify(pack.get("report_text")) or render_report_text(
            pack
        )
        if callable(fn) and report_text.strip():
            try:
                matches = fn(state_obj, report_text)
                text = _stringify([_as_dict(m) for m in matches])
                if text.strip() and text.strip() != "[]":
                    return text
            except Exception as exc:  # noqa: BLE001
                logger.debug("resolve_predictions unavailable: %s", exc)
        return _stringify(pending)

    def _build_prompt_kwargs(
        self,
        pack: dict[str, Any],
        state: dict[str, Any],
        state_obj: Any,
        lecture_no: int,
        as_of: str,
    ) -> dict[str, str]:
        """One shared kwargs dict; every template uses a subset of the keys.

        Pre-rendered keys in the pack win, so a hand-built pack dict (tests,
        future context_pack versions) can override any slot directly.
        """
        empty = "(자료 없음)"

        def slot(key: str, renderer: Any) -> str:
            direct = _stringify(pack.get(key))
            if direct.strip():
                return direct
            try:
                return renderer(pack) or empty
            except Exception as exc:  # noqa: BLE001
                logger.warning("masterclass: slot %s render failed: %s", key, exc)
                return empty

        return {
            "as_of": as_of,
            "year": str(self.year),
            "month": str(self.month),
            "lecture_no": str(lecture_no),
            "report_digest": slot("report_digest", render_report_digest),
            "factsheet": slot("factsheet", render_factsheet),
            "history_tables": slot("history_tables", render_history_tables),
            "prev_delta": slot("prev_delta", render_prev_delta),
            "prev_lecture_digest": (
                _stringify(pack.get("prev_lecture_digest"))
                or self._prev_lecture_digest()
                or empty
            ),
            "calendar": slot("calendar", render_calendar),
            "kcif_notes": _stringify(pack.get("kcif_notes")) or empty,
            "reader_level": str(state.get("reader_level") or "foundation"),
            "covered_topics": _stringify(state.get("covered_topics")) or "(없음)",
            "covered_glossary": _stringify(state.get("glossary")) or "(없음)",
            "topic_queue": _stringify(state.get("topic_queue")) or empty,
            "topic_suggestions": (
                self._topic_candidates(state_obj, pack) or empty
            ),
            "prev_predictions": (
                self._prev_predictions(state_obj, pack) or empty
            ),
            "topics_json": "{}",
            "outline": "",
            "lecture_md": "",
            "high_issues": "",
        }

    # ------------------------------------------------------------------
    # Stage 2 — topic selection
    # ------------------------------------------------------------------

    def _select_topics(
        self, kwargs: dict[str, str]
    ) -> tuple[dict[str, Any], str]:
        try:
            raw = self._call_claude(
                user_prompt=TOPIC_SELECTION_PROMPT.format(**kwargs),
                system_prompt=TOPIC_SELECTION_SYSTEM_PROMPT,
                timeout=self.TOPIC_TIMEOUT,
                label="topic_selection",
            )
        except Exception as exc:  # noqa: BLE001
            self._warn(f"주제 선정 콜 실패 ({exc}) — 큐 기반 대체 주제 사용")
            return self._fallback_topics(kwargs), ""

        topics = extract_json_block(raw, "TOPICS_JSON")
        outline = extract_marker_block(raw, "OUTLINE")
        if not isinstance(topics, dict) or not topics.get("topics"):
            self._warn("주제 JSON 파싱 실패 — 큐 기반 대체 주제 사용")
            topics = self._fallback_topics(kwargs)
        return topics, outline

    def _fallback_topics(self, kwargs: dict[str, str]) -> dict[str, Any]:
        queue = [
            line.strip("-* \t")
            for line in kwargs.get("topic_queue", "").splitlines()
            if line.strip("-* \t")
        ]
        tracks = ("macro", "macro", "politics")
        items = [
            {
                "id": queue[i] if i < len(queue) else f"topic-{i + 1}",
                "track": tracks[i],
                "chapter": i + 1,
                "title_ko": queue[i] if i < len(queue) else f"주제 {i + 1}",
                "depth": "core",
            }
            for i in range(3)
        ]
        return {"topics": items, "fallback": True}

    # ------------------------------------------------------------------
    # Stage 3 — parallel writing
    # ------------------------------------------------------------------

    async def _write_all(
        self, kwargs: dict[str, str]
    ) -> tuple[dict[int, str], dict[str, Any], dict[int, str]]:
        """Run the three writer calls concurrently.

        Returns (chapters, extras, status). ``status`` maps chapter number to
        ``"ok"`` or ``"placeholder"``.
        """
        specs = (
            ("macro", WRITE_MACRO_PROMPT),
            ("politics_history", WRITE_POLITICS_HISTORY_PROMPT),
            ("synthesis", WRITE_SYNTHESIS_PROMPT),
        )
        sem = asyncio.Semaphore(self.MAX_PARALLEL_WRITERS)

        async def _one(name: str, template: str) -> tuple[str, str]:
            async with sem:
                text = await asyncio.to_thread(
                    self._call_claude,
                    template.format(**kwargs),
                    WRITER_SYSTEM_PROMPT,
                    self.WRITE_TIMEOUT,
                    f"write_{name}",
                )
            return name, text

        results = await asyncio.gather(
            *(_one(name, tmpl) for name, tmpl in specs),
            return_exceptions=True,
        )

        chapters: dict[int, str] = {}
        status: dict[int, str] = {}
        extras: dict[str, Any] = {}
        failures: dict[str, str] = {}
        raw_by_writer: dict[str, str] = {}

        for spec, res in zip(specs, results, strict=False):
            name = spec[0]
            if isinstance(res, BaseException):
                failures[name] = str(res)
                self._warn(f"집필 콜 {name} 실패: {res}")
                continue
            raw_by_writer[name] = res[1]

        for name, owned in WRITER_CHAPTERS.items():
            raw = raw_by_writer.get(name, "")
            parsed = extract_chapters(raw, owned) if raw else {}
            for n in owned:
                body = parsed.get(n, "").strip()
                if body:
                    chapters[n] = body
                    status[n] = "ok"
                else:
                    reason = failures.get(name) or "마커 블록 누락"
                    chapters[n] = chapter_placeholder(
                        n, CHAPTER_TITLES.get(n, ""), reason
                    )
                    status[n] = "placeholder"
                    if name not in failures:
                        self._warn(f"{n}장 마커 블록 누락 — 자리표시자 삽입")

        synth_raw = raw_by_writer.get("synthesis", "")
        if synth_raw:
            extras["glossary_md"] = extract_marker_block(
                synth_raw, "GLOSSARY_MD"
            )
            gloss = extract_json_block(synth_raw, "GLOSSARY_JSON")
            if isinstance(gloss, dict):
                extras["glossary"] = gloss
            preds = extract_json_block(synth_raw, "PREDICTIONS_JSON")
            if isinstance(preds, dict):
                preds = preds.get("predictions")
            if isinstance(preds, list):
                extras["predictions"] = preds
        return chapters, extras, status

    # ------------------------------------------------------------------
    # Stage 4 — evaluator + revision
    # ------------------------------------------------------------------

    def _evaluate(
        self, markdown: str, kwargs: dict[str, str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        eval_kwargs = dict(kwargs)
        eval_kwargs["lecture_md"] = markdown
        try:
            raw = self._call_claude(
                user_prompt=EVALUATOR_PROMPT.format(**eval_kwargs),
                system_prompt=EVALUATOR_SYSTEM_PROMPT,
                timeout=self.EVALUATOR_TIMEOUT,
                label="evaluator",
            )
        except Exception as exc:  # noqa: BLE001
            self._warn(f"Evaluator 실패 (non-fatal): {exc}")
            return [], []

        payload = extract_json_block(raw, "ISSUES_JSON")
        if payload is None:
            self._warn("Evaluator 이슈 JSON 파싱 실패 — 결함 없음으로 간주")
            return [], []
        items = payload.get("issues") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return [], []
        high = high_issues_from(items)
        medium = [
            it
            for it in items
            if isinstance(it, dict)
            and str(it.get("severity", "")).strip().upper() == "MEDIUM"
        ]
        logger.info(
            "Masterclass evaluator: HIGH=%d MEDIUM=%d", len(high), len(medium)
        )
        return high, medium

    def _revise(
        self,
        markdown: str,
        high: list[dict[str, Any]],
        chapters: dict[int, str],
        kwargs: dict[str, str],
        glossary_md: str,
        lecture_no: int,
        as_of: str,
        topics: dict[str, Any],
        status: dict[int, str],
    ) -> str:
        """One revision round; returns the reassembled markdown or ``""``."""
        rev_kwargs = dict(kwargs)
        rev_kwargs["lecture_md"] = markdown
        rev_kwargs["high_issues"] = format_issues(high)
        try:
            raw = self._call_claude(
                user_prompt=REVISION_PROMPT.format(**rev_kwargs),
                system_prompt=REVISION_SYSTEM_PROMPT,
                timeout=self.REVISION_TIMEOUT,
                label="revision_r2",
            )
        except Exception as exc:  # noqa: BLE001
            self._warn(f"R2 수정 콜 실패 (non-fatal): {exc}")
            return ""

        revised_chapters = extract_chapters(raw)
        new_glossary = extract_marker_block(raw, "GLOSSARY_MD")
        if not revised_chapters and not new_glossary:
            self._warn("R2 응답에 마커 블록 없음 — 원본 유지")
            return ""

        merged = dict(chapters)
        for n, body in revised_chapters.items():
            if body.strip():
                merged[n] = body.strip()
                status[n] = "revised"
        logger.info(
            "Masterclass: R2 applied to chapters %s",
            sorted(revised_chapters),
        )
        return assemble_lecture(
            merged,
            lecture_no=lecture_no,
            year=self.year,
            month=self.month,
            as_of=as_of,
            topics=topics,
            glossary_md=new_glossary or glossary_md,
        )

    # ------------------------------------------------------------------
    # Stage 5 — advisory gates
    # ------------------------------------------------------------------

    def _run_gates(self, markdown: str) -> dict[str, list[str]]:
        """Temporal + numeric screens. Advisory only — never raises/blocks."""
        findings: dict[str, list[str]] = {"temporal": [], "numeric": []}

        try:
            from indepth_analysis.temporal_lint import scan_temporal_issues

            temporal = scan_temporal_issues(markdown, self.year)
            findings["temporal"] = [
                f"L{f.line_no} [{f.severity}] {f.text}"
                for f in temporal
                if f.severity in ("high", "medium")
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("temporal lint skipped: %s", exc)

        try:
            from indepth_analysis.numeric_audit import (
                build_default_sources,
                scan_numeric_issues,
            )

            sources = build_default_sources()
            numeric = scan_numeric_issues(
                markdown, as_of=self._month_end(), sources=sources
            )
            findings["numeric"] = [
                f"L{getattr(f, 'line_no', '?')} "
                f"[{getattr(f, 'severity', '?')}] "
                f"{getattr(f, 'indicator', '')}"
                for f in numeric
                if str(getattr(f, "severity", "")).lower() == "high"
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("numeric audit skipped: %s", exc)

        for kind, items in findings.items():
            if items:
                logger.warning(
                    "Masterclass %s gate (advisory, 발행 차단 없음): %d건",
                    kind,
                    len(items),
                )
        return findings

    # ------------------------------------------------------------------
    # Curriculum update
    # ------------------------------------------------------------------

    def _record_curriculum(
        self,
        state_obj: Any,
        *,
        topics: dict[str, Any],
        glossary: dict[str, Any],
        predictions: list[dict[str, Any]],
    ) -> None:
        """Transition + persist the curriculum state (non-fatal on failure)."""
        mod = self._curriculum_module()
        if mod is None:
            return
        try:
            selected = self._selected_topics(mod, topics)
            glossary_map = curriculum_glossary(glossary)
            pred_list = curriculum_predictions(predictions)
            new_state = _try_variants(
                mod.record_lecture,
                [
                    ((state_obj, selected, glossary_map, pred_list), {}),
                    (
                        (state_obj, selected),
                        {
                            "new_glossary": glossary_map,
                            "predictions": pred_list,
                        },
                    ),
                ],
            )
        except Exception as exc:  # noqa: BLE001
            self._warn(f"커리큘럼 기록 실패 (non-fatal): {exc}")
            return

        state_to_save = new_state if new_state is not None else state_obj
        try:
            _try_variants(
                mod.save_state,
                [((state_to_save, self.state_path), {}), ((state_to_save,), {})],
            )
        except Exception as exc:  # noqa: BLE001
            self._warn(f"커리큘럼 저장 실패 (non-fatal): {exc}")

    @staticmethod
    def _selected_topics(mod: Any, topics: dict[str, Any]) -> list[Any]:
        """Coerce the Stage 2 topics JSON into the curriculum's topic model."""
        items = topics.get("topics") if isinstance(topics, dict) else None
        rows = curriculum_topics(items if isinstance(items, list) else [])
        model = getattr(mod, "SelectedTopic", None)
        if model is None:
            return rows
        out = []
        for row in rows:
            try:
                out.append(model.model_validate(row))
            except Exception as exc:  # noqa: BLE001
                logger.warning("masterclass: topic %s dropped (%s)", row, exc)
        return out

    # ------------------------------------------------------------------
    # Claude CLI
    # ------------------------------------------------------------------

    def _call_claude(
        self,
        user_prompt: str,
        system_prompt: str,
        timeout: int,
        label: str,
        retries: int = 1,
    ) -> str:
        """Claude CLI call with one retry; no extra tools (pure generation)."""
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                text = self._exec_claude(
                    user_prompt, system_prompt, timeout, label
                )
                if text.strip():
                    return text
                last_exc = RuntimeError(f"empty output from {label}")
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            if attempt < retries:
                logger.warning(
                    "Masterclass %s attempt %d failed (%s) — retrying",
                    label,
                    attempt + 1,
                    last_exc,
                )
        raise RuntimeError(f"Claude CLI ({label}) failed: {last_exc}")

    def _exec_claude(
        self,
        user_prompt: str,
        system_prompt: str,
        timeout: int,
        label: str,
    ) -> str:
        """Single ``claude -p`` subprocess round-trip. Returns parsed text."""
        cmd = [
            "claude",
            "-p", user_prompt,
            "--append-system-prompt", system_prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.model,
        ]
        logger.info("Masterclass %s: calling Claude CLI", label)
        with span(
            project="indepth_analysis",
            provider="anthropic",
            model=self.model,
            call_kind=CallKind.CLI_SUBPROCESS,
            function_name="MasterclassOrchestrator._exec_claude",
            tags={"label": label},
        ) as obs_handle:
            obs_handle.set_text_len(
                len(user_prompt), system_len=len(system_prompt)
            )
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(Path("/tmp")),
                )
            except FileNotFoundError as exc:
                obs_handle.set_error("claude CLI not found")
                raise RuntimeError(
                    "claude CLI not found in PATH — is it installed?"
                ) from exc

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                obs_handle.set_error("timeout")
                raise RuntimeError(
                    f"Claude CLI ({label}) timed out after {timeout}s"
                ) from None

            if proc.returncode != 0:
                obs_handle.set_error(f"exit {proc.returncode}")
                raise RuntimeError(
                    f"Claude CLI ({label}) failed (exit {proc.returncode}): "
                    f"{(stderr or '')[:500]}"
                )

            try:
                cli_result = parse_stream_json_text(stdout)
                obs_handle.set_usage(cli_result.usage)
            except Exception:  # noqa: BLE001
                logger.debug("usage extraction failed for masterclass %s", label)

        return parse_stream_json(stdout)

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------

    def _warn(self, message: str) -> None:
        logger.warning("Masterclass: %s", message)
        self.warnings.append(message)


# ---------------------------------------------------------------------------
# stream-json parsing (house convention)
# ---------------------------------------------------------------------------


def parse_stream_json(raw: bytes | str) -> str:
    """Collect assistant text from stream-json output, fallback to result."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")

    text_parts: list[str] = []
    result_text = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = obj.get("type", "")
        if kind == "assistant":
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
        elif kind == "result" and obj.get("subtype") == "success":
            candidate = (obj.get("result") or "").strip()
            if candidate:
                result_text = candidate
    return result_text or "".join(text_parts)


# ---------------------------------------------------------------------------
# Small utilities (TE1 interface tolerance)
# ---------------------------------------------------------------------------


def _as_dict(obj: Any) -> dict[str, Any]:
    """Coerce a context pack / curriculum state into a plain dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "to_dict", "as_dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                out = fn()
                if isinstance(out, dict):
                    return out
            except Exception:  # noqa: BLE001
                continue
    try:
        import dataclasses

        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
    except Exception:  # noqa: BLE001
        pass
    data = getattr(obj, "__dict__", None)
    return dict(data) if isinstance(data, dict) else {}


def _try_variants(fn: Any, variants: list[tuple[tuple, dict]]) -> Any:
    """Call ``fn`` with the first argument shape it accepts."""
    last: Exception | None = None
    for args, kwargs in variants:
        try:
            return fn(*args, **kwargs)
        except TypeError as exc:
            last = exc
            continue
    raise last if last else RuntimeError("no call variant succeeded")


def _stringify(value: Any) -> str:
    """Render a prompt slot value as text (markdown passthrough for str)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list | dict):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _fallback_state() -> dict[str, Any]:
    """Minimal curriculum state used when the TE1 module is unavailable."""
    return {
        "lecture_no": 0,
        "covered_topics": [],
        "topic_queue": [],
        "glossary": {},
        "reader_level": "foundation",
        "predictions": [],
    }
