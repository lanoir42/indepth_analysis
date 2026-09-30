"""v3 WP1 Intake — 파싱·중복/조각·멱등·계약 검증 (네트워크·LLM 없음)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from indepth_analysis.skills.euro_macro.monthly_brief import cards, intake
from indepth_analysis.skills.euro_macro.monthly_brief.contract import (
    validate_card,
    validate_session,
)
from indepth_analysis.skills.euro_macro.monthly_brief.edition import Edition

DISCLAIMER = (
    "This document is being provided for the exclusive use of GEUMIL BAE at NC "
    "CORPORATION. Not for redistribution.\n"
    "Bloomberg\n"
    "This report may not be modified or altered in any way. The BLOOMBERG "
    "PROFESSIONAL service\n"
    "advice, and nothing herein shall constitute an offer of financial "
    "instruments by BFLP, BLP or their affiliates.\n"
    "Bloomberg ®\n"
    "Printed on {printed}\n"
    "Page 1 of 1\n"
    "News Story\n"
)


def story(
    stamp: str, title: str, by: str, body: str, printed: str = "09/29/2026"
) -> str:
    return (
        f"{stamp} [BI] Bloomberg Intelligence\n{title}\nBy {by}\n"
        f"(Bloomberg Economics) -- {body}\n"
        "To contact the economist on this analysis:\n"
        "David Powell (Economist) in London at dpowell24@bloomberg.net\n"
        + DISCLAIMER.format(printed=printed)
    )


def web(title: str, body: str, stamp: str = "(09/25/26)") -> str:
    return (
        "Megan O'Neil\nTeam: Economics\nBI Research Editor\nLatest\n"
        "Table of Contents\nGlobal Economic Analysis - Wrap\n"
        f"1. {title}\n(Bloomberg Intelligence) -- {body} {stamp}\n"
        "Bloomberg® 09/29/2026 22:57:21\n"
    )


def write_md(folder: Path, name: str, mtitle: str, pages: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    parts = [f"# {mtitle}\n\n(pages={len(pages)}; file={name}.pdf)\n"]
    for i, p in enumerate(pages, 1):
        parts.append(f"\n---\n## p.{i}\n\n{p}")
    md = folder / f"{name}.md"
    md.write_text("".join(parts), encoding="utf-8")
    (folder / f"{name}.pdf").write_bytes(b"%PDF-1.4 fake")
    return md


LONG = (
    "The euro-area economy is sailing through the third quarter with improved "
    "momentum. Inflation rose to 3.3% in August from 2.9% in July, while core "
    "inflation eased to 2.4%. The ECB is expected to raise the deposit rate. "
) * 4


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------


def test_parse_bi_story_header():
    p1 = story(
        "08/27/2026    01:33:27",
        "AI’s Jobs Shakeup Has Yet to Arrive: Fault Lines",
        "Antonio Barroso (Analyst)",
        "Welcome to Fault Lines",
    )
    h = intake.parse_header(p1, "AIs_Jobs.pdf")
    assert h["fmt"] == "bi_story"
    assert h["published_at"] == "2026-08-27T01:33"
    assert h["title"] == "AI’s Jobs Shakeup Has Yet to Arrive: Fault Lines"
    assert h["author"] == "Antonio Barroso"
    assert intake.classify_series(h["title"]) == "FAULT_LINES"


def test_parse_two_authors_and_prefix_classification():
    p1 = story(
        "09/10/2026    23:57:32",
        "ECB REACT: Hawkish Tone, Forecast Changes Flag December Hike (2)",
        "David Powell (Economist) and Simona Delle Chiaie (Economist)",
        "x",
    )
    h = intake.parse_header(p1)
    assert h["author"] == "David Powell, Simona Delle Chiaie"
    assert intake.classify_series(h["title"]) == "REACT"
    assert intake.classify_geo(h["title"]) == "ECB"
    t = "EURO-AREA PREVIEW: Muted Core Inflation May Curb ECB Hawks (1)"
    assert intake.classify_series(t) == "PREVIEW"
    assert intake.classify_geo(t) == "EA"
    groups = intake.classify_groups(t, "", "EA")
    assert groups[0] == "EA_MACRO" and "ECB" in groups
    assert intake.classify_series("EMEA WEEK AHEAD: Ifo, PMI to Take") == "WEEK_AHEAD"


def test_parse_web_export_header_and_stamp_date():
    p1 = web("Fed Hike, UK CPI Rise, German Industry's China Woes: Eco Wrap", "x")
    h = intake.parse_header(p1, "Fed_Hike.pdf")
    assert h["fmt"] == "bi_web"
    assert h["title"].endswith("Eco Wrap")
    assert h["author"] == "Megan O'Neil"
    assert intake._max_stamp("a (09/18/26) b (09/25/26) c (08/30/26)") == "2026-09-25"
    s = intake.classify_series(h["title"], h["label"])
    assert s == "ECO_WRAP"
    assert intake.classify_geo(h["title"], h["label"], s) == "GLOBAL"


def test_clean_lines_strips_boilerplate():
    p1 = story("09/01/2026    14:00:00", "T", "A (Economist)", "Body text")
    lines = intake.clean_lines(p1)
    joined = "\n".join(lines)
    assert "exclusive use" not in joined
    assert "BFLP" not in joined and "Printed on" not in joined
    assert "bloomberg.net" not in joined and "To contact" not in joined
    assert "Body text" in joined


def test_sha_ignores_print_time():
    a = story("09/01/2026    14:00:00", "T", "A", LONG, printed="09/10/2026")
    b = story("09/01/2026    14:00:00", "T", "A", LONG, printed="09/29/2026")
    sa = intake.sha16_of("\n".join(intake.clean_lines(a)))
    sb = intake.sha16_of("\n".join(intake.clean_lines(b)))
    assert sa == sb and len(sa) == 16


# ---------------------------------------------------------------------------
# 중복·조각 + 스캐폴드 멱등
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    base = tmp_path / "references" / "mendeley_europe"
    aug, sep = base / "202608", base / "202609"
    same = story(
        "09/07/2026    17:27:00",
        "EUROPE REACT: AfD Win Poses New Test for Mainstream Politics",
        "Antonio Barroso (Analyst)",
        LONG + " AfD Merz Germany politics.",
    )
    write_md(aug, "EUROPE_REACT_AfD_Win", "EUROPE REACT: AfD Win", [same])
    write_md(
        aug,
        "ECB_PREVIEW_Old",
        "ECB PREVIEW: Old",
        [story("08/20/2026    14:00:00", "ECB PREVIEW: Old Story", "D P", LONG)],
    )
    # 9월 컬렉션: 전월 재수록(인쇄 시각만 다름)
    write_md(
        sep,
        "EUROPE_REACT_AfD_Win",
        "EUROPE REACT: AfD Win",
        [same.replace("Printed on 09/29/2026", "Printed on 09/30/2026")],
    )
    # 신규
    write_md(
        sep,
        "FRANCE_INSIGHT_Spread",
        "FRANCE INSIGHT: Spread",
        [
            story(
                "09/21/2026    16:45:18",
                "FRANCE INSIGHT: Spread Spike Darkens Fiscal, Growth Outlook (1)",
                "Jean Dalbard (Economist)",
                LONG + " France OAT spread Lecornu budget.",
            )
        ],
    )
    # 같은 제목+시각의 개정본(본문 약간 다름) → same_title_time
    write_md(
        sep,
        "FRANCE_INSIGHT_Spread_v2",
        "FRANCE INSIGHT: Spread",
        [
            story(
                "09/21/2026    16:45:18",
                "FRANCE INSIGHT: Spread Spike Darkens Fiscal, Growth Outlook (2)",
                "Jean Dalbard (Economist)",
                LONG + " France OAT spread Lecornu budget. Updated.",
            )
        ],
    )
    # 창 이전 발행(재업로드) → stale
    write_md(
        sep,
        "UK_OLD",
        "UK INSIGHT: Old",
        [story("08/05/2026    14:00:00", "UK INSIGHT: Old Gilt Story", "M B", LONG)],
    )
    # 모음물 판본 2개(상호 포함) → near_dup_compilation
    items = "\n".join(
        f"{i}. Item {i} headline about euro-area markets and policy\n{LONG}"
        f" unique line number {i} for this item body text ok"
        for i in range(2, 8)
    )
    write_md(
        sep,
        "Wrap_A",
        "chart caption",
        [web("Wrap A: Eco Wrap", "Intro A", "(09/16/26)") + items],
    )
    write_md(
        sep,
        "Wrap_B",
        "chart caption",
        [web("Wrap B: Eco Wrap", "Intro B", "(09/16/26)") + items],
    )
    # 헤더 없는 캡션 조각
    write_md(sep, "G7_Borrowing", "G7 Borrowing Costs", ["G7 Borrowing Costs\nSource"])
    return tmp_path


def _ed() -> Edition:
    return Edition(
        month="2026-09",
        phase="preview",
        as_of="2026-10-02",
        report_date="2026-10-05",
        root="reports/euro_macro/monthly_brief/2026-09",
    )


def test_dups_fragments_stale(repo: Path):
    s = intake.scaffold(_ed(), repo_root=repo)
    by_title = {d["title"]: d for d in s["documents"]}
    afd = by_title["EUROPE REACT: AfD Win Poses New Test for Mainstream Politics"]
    assert afd["prior_collection"] == "EUROPE 202608"
    fr1 = by_title["FRANCE INSIGHT: Spread Spike Darkens Fiscal, Growth Outlook (1)"]
    fr2 = by_title["FRANCE INSIGHT: Spread Spike Darkens Fiscal, Growth Outlook (2)"]
    assert fr1["dup_of"] is None and fr2["dup_of"] == fr1["sha16"]
    assert fr2["dup_reason"] == "same_title_time"
    assert by_title["UK INSIGHT: Old Gilt Story"]["stale"] is True
    wa, wb = by_title["Wrap A: Eco Wrap"], by_title["Wrap B: Eco Wrap"]
    assert {wa["dup_reason"], wb["dup_reason"]} == {"near_dup_compilation", None}
    frag = [d for d in s["documents"] if d["fragment"]]
    assert len(frag) == 1 and frag[0]["card_sha16"] is None
    # 8월 문서(창 밖)는 세션에 없음
    assert "ECB PREVIEW: Old Story" not in by_title
    # 중복·조각은 uncarded에 없음; 원본만
    assert fr2["sha16"] not in s["uncarded"]
    assert frag[0]["sha16"] not in s["uncarded"]
    assert fr1["sha16"] in s["uncarded"]
    assert fr1["groups"][0] == "FR"


def test_scaffold_idempotent_and_valid(repo: Path):
    ed = _ed()
    s1 = intake.scaffold(ed, repo_root=repo)
    root = repo / ed.root
    sec = root / "sections" / "FR.md"
    assert sec.read_text().rstrip().endswith(intake.NARRATIVE)
    # Opus 단계가 서술을 채운 뒤에도 재스캐폴드가 서술을 보존
    sec.write_text(
        sec.read_text().replace(intake.NARRATIVE, "## 서술\n본문"), encoding="utf-8"
    )
    snap = (root / "documents" / "doc_cards.md").read_text()
    s2 = intake.scaffold(ed, repo_root=repo)
    assert "## 서술\n본문" in sec.read_text()
    assert (root / "documents" / "doc_cards.md").read_text() == snap
    strip = lambda s: {k: v for k, v in s.items() if k != "generated_at"}  # noqa: E731
    assert strip(s1) == strip(s2)
    validate_session(root / "session.json", repo_root=repo)
    with sqlite3.connect(repo / intake.DB_PATH) as c:
        n = c.execute("SELECT COUNT(*) FROM europe_docs").fetchone()[0]
        fs = c.execute(
            "SELECT first_seen_collection, collection FROM europe_docs "
            "WHERE title LIKE 'EUROPE REACT: AfD%'"
        ).fetchone()
    assert fs == ("EUROPE 202608", "EUROPE 202609")
    s3 = intake.scaffold(ed, repo_root=repo)
    with sqlite3.connect(repo / intake.DB_PATH) as c:
        assert c.execute("SELECT COUNT(*) FROM europe_docs").fetchone()[0] == n
    assert len(s3["documents"]) == len(s1["documents"])
    # 절대경로 링크
    assert str(repo.resolve()) in (root / "documents" / "doc_cards.md").read_text()


def test_card_shrinks_uncarded(repo: Path):
    ed = _ed()
    s = intake.scaffold(ed, repo_root=repo)
    target = s["uncarded"][0]
    doc = next(d for d in intake.collect(ed, repo) if d.sha16 == target)
    raw = {
        "title_ko": "테스트 카드 제목",
        "groups": ["FR", "BOGUS"],
        "summary_ko": ["첫 불릿 요지임.", "둘째 불릿 요지임."],
        "key_numbers": [
            {
                "metric": "HICP",
                "geo": "EA",
                "period": "2026-08",
                "value": 3.3,
                "unit": "% YoY",
                "kind": "actual",
                "note": None,
            },
            {"metric": "invented", "value": 9.87, "kind": "actual"},
        ],
        "claims": [],
        "forecasts": [],
        "politics": [],
        "importance": 3,
    }
    card = cards.assemble(doc, raw, "sonnet")
    assert card["groups"] == ["FR"]
    validate_card(card)
    bad = cards.unverified(card, doc.body)
    assert [b["metric"] for b in bad] == ["invented"]
    out = repo / intake.CARDS_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{target}.json").write_text(json.dumps(card), encoding="utf-8")
    s2 = intake.scaffold(ed, repo_root=repo)
    assert target not in s2["uncarded"]
    assert len(s2["uncarded"]) == len(s["uncarded"]) - 1
    assert "테스트 카드 제목" in (repo / ed.root / "documents/doc_cards.md").read_text()


def test_card_validation_rejects_bad():
    base = {
        "sha16": "0123456789abcdef",
        "title_ko": "한국어 제목",
        "series": "REACT",
        "geo": "EA",
        "groups": ["EA_MACRO"],
        "summary_ko": ["요지 하나임.", "요지 둘임."],
        "importance": 3,
        "card_model": "sonnet",
    }
    validate_card(base)
    for patch in (
        {"groups": ["EA_INFLATION"]},
        {"summary_ko": ["English only", "also english"]},
        {"importance": 7},
        {"sha16": "xyz"},
        {"key_numbers": [{"metric": "m", "value": "n/a", "kind": "actual"}]},
    ):
        with pytest.raises(ValueError):
            validate_card({**base, **patch})


def test_excerpt_prefers_europe_items():
    items = ["intro line"] + [
        f"{i}. {'US payrolls jobs' if i % 2 else 'ECB euro-area HICP'} item\n"
        + "x" * 3000
        for i in range(2, 12)
    ]
    body = "\n".join(items)
    ex, cut = cards.excerpt(body, limit=12_000)
    assert cut and len(ex) <= 12_000
    assert ex.count("ECB euro-area") > ex.count("US payrolls")


def test_parse_json_fenced():
    assert cards.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert cards.parse_json('앞말 {"a": [1,2]} 뒷말') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        cards.parse_json("no json")
