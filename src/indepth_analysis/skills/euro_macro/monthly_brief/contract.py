"""v3 WP1 파일 계약 — session.json·문서 카드 스키마(pydantic).

정본 기술: ``docs/euro_macro_monthly_brief/V3_CONTRACTS.md`` §2.

    from indepth_analysis.skills.euro_macro.monthly_brief.contract import (
        validate_session, validate_card, Card, Session,
    )

- ``validate_session(path)`` → ``Session`` (실패 시 ``pydantic.ValidationError``)
- ``validate_card(dict)`` → ``Card`` (LLM 출력 검증·저장 전 검사)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

GROUPS = (
    "ECB",
    "EA_MACRO",
    "DE",
    "FR",
    "IT",
    "ES",
    "UK",
    "EU_POLICY",
    "ENERGY_EXTERNAL",
    "GLOBAL",
)
SERIES = (
    "PREVIEW",
    "REACT",
    "INSIGHT",
    "WEEK_AHEAD",
    "FAULT_LINES",
    "ECO_WRAP",
    "OUTLOOK",
    "PRIMER",
    "OTHER",
)
GEOS = ("EA", "DE", "FR", "IT", "ES", "UK", "EU", "ECB", "GLOBAL", "US", "CN", "OTHER")
CARD_VERSION = "3.0"

Group = Literal[
    "ECB",
    "EA_MACRO",
    "DE",
    "FR",
    "IT",
    "ES",
    "UK",
    "EU_POLICY",
    "ENERGY_EXTERNAL",
    "GLOBAL",
]
Series = Literal[
    "PREVIEW",
    "REACT",
    "INSIGHT",
    "WEEK_AHEAD",
    "FAULT_LINES",
    "ECO_WRAP",
    "OUTLOOK",
    "PRIMER",
    "OTHER",
]
Geo = Literal[
    "EA", "DE", "FR", "IT", "ES", "UK", "EU", "ECB", "GLOBAL", "US", "CN", "OTHER"
]

_SHA16 = re.compile(r"^[0-9a-f]{16}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?$")
_HANGUL = re.compile(r"[가-힣]")


def _sha(v: str | None) -> str | None:
    if v is not None and not _SHA16.match(v):
        raise ValueError(f"sha16 형식 아님: {v!r}")
    return v


# ---------------------------------------------------------------------------
# 문서 카드
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyNumber(_Strict):
    metric: str = Field(min_length=1)
    geo: str = ""
    period: str = ""
    value: float
    unit: str = ""
    kind: Literal["actual", "forecast", "consensus", "estimate"]
    note: str = ""


class Claim(_Strict):
    claim_ko: str = Field(min_length=2)
    stance: Literal["hawkish", "dovish", "upside", "downside", "neutral"]
    horizon: str = ""
    confidence: Literal["high", "mid", "low"]


class Forecast(_Strict):
    variable: str = Field(min_length=1)
    value: float | str
    by: str = ""
    source_view: str = "BI"


class Politics(_Strict):
    country: str = Field(min_length=2)
    actors: list[str] = Field(default_factory=list)
    event: str = Field(min_length=2)
    date: str = ""


class Card(BaseModel):
    """문서 카드. ``unverified_numbers``·``text_excerpted``는 결정론 검사 부가 필드."""

    model_config = ConfigDict(extra="allow")

    sha16: str
    title_ko: str = Field(min_length=2)
    published_at: str | None = None
    series: Series
    geo: Geo
    groups: list[Group] = Field(min_length=1, max_length=4)
    summary_ko: list[str] = Field(min_length=2, max_length=6)
    key_numbers: list[KeyNumber] = Field(default_factory=list, max_length=12)
    claims: list[Claim] = Field(default_factory=list, max_length=6)
    forecasts: list[Forecast] = Field(default_factory=list, max_length=8)
    politics: list[Politics] = Field(default_factory=list, max_length=10)
    importance: int = Field(ge=1, le=5)
    card_model: str
    card_version: str = CARD_VERSION

    @field_validator("sha16")
    @classmethod
    def _v_sha(cls, v: str) -> str:
        return _sha(v)

    @field_validator("summary_ko")
    @classmethod
    def _korean(cls, v: list[str]) -> list[str]:
        for s in v:
            if not _HANGUL.search(s):
                raise ValueError(f"summary_ko 불릿이 한국어가 아님: {s[:40]!r}")
        return v

    @field_validator("title_ko")
    @classmethod
    def _title_ko(cls, v: str) -> str:
        if not _HANGUL.search(v):
            raise ValueError("title_ko가 한국어가 아님")
        return v

    @field_validator("groups")
    @classmethod
    def _uniq(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("groups 중복")
        return v


def validate_card(data: dict) -> Card:
    return Card.model_validate(data)


# ---------------------------------------------------------------------------
# session.json
# ---------------------------------------------------------------------------


class Period(_Strict):
    from_: str = Field(alias="from")
    to: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("from_", "to")
    @classmethod
    def _d(cls, v: str) -> str:
        if not _DATE.match(v):
            raise ValueError(f"날짜 형식 아님: {v!r}")
        return v


class GroupCovered(_Strict):
    group: Group
    n_docs: int = Field(ge=0)
    section: str
    latest_doc: str | None = None


class Document(BaseModel):
    model_config = ConfigDict(extra="allow")

    sha16: str
    series: Series
    geo: Geo
    groups: list[Group] = Field(min_length=1)
    date: str | None
    title: str = Field(min_length=1)
    path: str
    card: bool
    dup_of: str | None = None
    fragment: bool = False

    @field_validator("sha16", "dup_of")
    @classmethod
    def _v_sha(cls, v: str | None) -> str | None:
        return _sha(v)

    @field_validator("date")
    @classmethod
    def _v_date(cls, v: str | None) -> str | None:
        if v is not None and not _ISO.match(v):
            raise ValueError(f"date 형식 아님: {v!r}")
        return v

    @field_validator("path")
    @classmethod
    def _rel(cls, v: str) -> str:
        if v.startswith("/"):
            raise ValueError("session.json 경로는 저장소 루트 기준 상대경로")
        return v


class SessionData(BaseModel):
    model_config = ConfigDict(extra="allow")
    chart_pack: str
    table_pack: str


class Session(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_type: Literal["europe_monthly"]
    ticker: Literal["EUROPE"]
    session_name: str
    collection: str = Field(pattern=r"^EUROPE \d{6}$")
    period: Period
    phase: Literal["preview", "interim", "final"]
    phases: dict
    groups_covered: list[GroupCovered]
    documents: list[Document]
    uncarded: list[str]
    data: SessionData
    generated_at: str
    pipeline_version: str

    @field_validator("uncarded")
    @classmethod
    def _unc(cls, v: list[str]) -> list[str]:
        for s in v:
            _sha(s)
        return v


def validate_session(path: str | Path, *, repo_root: str | Path | None = None):
    """session.json 스키마 + 교차 정합(uncarded ⊆ documents, 섹션 파일 존재)."""
    p = Path(path)
    s = Session.model_validate(json.loads(p.read_text(encoding="utf-8")))
    shas = {d.sha16 for d in s.documents}
    extra = [u for u in s.uncarded if u not in shas and not _dup_target(s, u)]
    if extra:
        raise ValueError(f"uncarded에 documents 밖 sha16: {extra}")
    root = p.parent
    for g in s.groups_covered:
        if not (root / g.section).exists():
            raise ValueError(f"섹션 파일 없음: {g.section}")
    if repo_root is not None:
        rr = Path(repo_root)
        missing = [d.path for d in s.documents if not (rr / d.path).exists()]
        if missing:
            raise ValueError(f"문서 경로 없음: {missing[:3]}")
    return s


def _dup_target(s: Session, sha: str) -> bool:
    return any(d.dup_of == sha for d in s.documents)
