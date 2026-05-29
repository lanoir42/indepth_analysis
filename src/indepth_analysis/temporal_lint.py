"""Deterministic temporal/anachronism lint for research reports.

A fast, dependency-free first-pass screen that flags lines mentioning a
calendar year other than the report's as-of year — the pattern behind the
"last year's event written as if it happened now" failure mode (e.g. a
2025-05 trade deal described as a 2026-05 event).

This is a *screen for human/LLM review*, not a hard gate: it has no network
access and cannot know whether a prior-year mention is a legitimate historical
reference or a genuine anachronism. It ranks lines so the high-signal cases
(off-year token sitting next to present/recency framing, and not part of an
obvious date range/time series) surface first.

Used by:
- CLI: ``uv run indepth lint-temporal <file> [--as-of YYYY-MM-DD]``
- Pipelines may call ``scan_temporal_issues`` as a deterministic pre-evaluator
  gate before the LLM Anachronism check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Match plausible calendar years 1900-2099 as standalone tokens.
_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")

# Present / recency framing cues (Korean + English). An off-year token on the
# same line as one of these is the classic anachronism smell.
_RECENCY_CUES: tuple[str, ...] = (
    "최근",
    "이번",
    "이달",
    "금월",
    "올해",
    "금년",
    "현재",
    "오늘",
    "지금",
    "방금",
    "막 ",
    "들어",
    "현시점",
    "최신",
    "latest",
    "recently",
    "currently",
    "this month",
    "this week",
    "this year",
    "today",
)

# Range / time-series markers — when present with multiple years, the
# prior-year mention is very likely a legitimate span (e.g. "2024-01~2026-04"),
# so we down-rank to avoid drowning the signal in noise.
_RANGE_MARKERS: tuple[str, ...] = ("~", "→", "부터", "이후", "이래", "—", " to ", "-")


class TemporalGateError(Exception):
    """Raised when a temporal gate finds HIGH-severity anachronism candidates."""

    def __init__(self, findings: list[TemporalFinding], as_of_year: int) -> None:
        self.findings = findings
        self.as_of_year = as_of_year
        super().__init__(
            f"{len(findings)}건의 HIGH 시점 정합성 이슈 — 발행 전 검토 필요"
        )


def infer_report_year(text: str, *, lines: int = 8) -> int | None:
    """Best-effort report year from the first ``lines`` lines (title/header)."""
    head = "\n".join(text.splitlines()[:lines])
    m = _YEAR_RE.search(head)
    return int(m.group()) if m else None


def assert_no_high(
    text: str,
    as_of_year: int,
    *,
    window_years: int = 0,
) -> None:
    """Raise :class:`TemporalGateError` if any HIGH finding exists.

    Used as a deterministic pre-publish gate (CLI + pipelines).
    """
    findings = scan_temporal_issues(text, as_of_year, window_years=window_years)
    high = [f for f in findings if f.severity == "high"]
    if high:
        raise TemporalGateError(high, as_of_year)


@dataclass
class TemporalFinding:
    """One suspect line. ``severity`` is review-priority, not correctness."""

    line_no: int
    years: list[int]
    severity: str  # "high" | "medium" | "low"
    cue: str | None
    text: str


def scan_temporal_issues(
    text: str,
    as_of_year: int,
    *,
    window_years: int = 0,
) -> list[TemporalFinding]:
    """Flag lines mentioning a year outside ``[as_of_year - window_years, as_of_year]``.

    severity:
      - "high":   off-year + recency cue, not an obvious range → likely anachronism
      - "medium": off-year + recency cue but inside a range/series line
      - "low":    off-year with no recency cue (probably historical context)
    """
    findings: list[TemporalFinding] = []
    lo = as_of_year - window_years
    for i, line in enumerate(text.splitlines(), start=1):
        years = sorted({int(m.group()) for m in _YEAR_RE.finditer(line)})
        off = [y for y in years if y < lo or y > as_of_year]
        if not off:
            continue
        cue = next((c for c in _RECENCY_CUES if c in line), None)
        has_range = len(years) >= 2 or any(m in line for m in _RANGE_MARKERS)
        if cue and not has_range:
            sev = "high"
        elif cue:
            sev = "medium"
        else:
            sev = "low"
        findings.append(
            TemporalFinding(
                line_no=i,
                years=off,
                severity=sev,
                cue=cue,
                text=line.strip()[:200],
            )
        )
    return findings


def render_report(findings: list[TemporalFinding], as_of_year: int) -> str:
    """Human-readable summary, high-severity first."""
    if not findings:
        return f"시점 lint: 기준연도 {as_of_year} 외 연도 언급 없음 (clean)."

    order = {"high": 0, "medium": 1, "low": 2}
    findings = sorted(findings, key=lambda f: (order[f.severity], f.line_no))
    counts = {s: sum(1 for f in findings if f.severity == s) for s in order}

    lines = [
        f"시점 lint (as-of {as_of_year}): "
        f"HIGH {counts['high']} / MEDIUM {counts['medium']} / LOW {counts['low']}",
        "  (HIGH = 타 연도 + 현재형 표현 동반 → 시대착오 의심; 수동 검토 필요)",
        "",
    ]
    for f in findings:
        tag = {"high": "🔴", "medium": "🟡", "low": "⚪"}[f.severity]
        yrs = ",".join(str(y) for y in f.years)
        cue = f" [cue: {f.cue.strip()}]" if f.cue else ""
        lines.append(f"{tag} L{f.line_no} (연도 {yrs}){cue}: {f.text}")
    return "\n".join(lines)
