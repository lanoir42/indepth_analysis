"""v3 edition·게이트·허브 — 네트워크·LLM 없이."""

from __future__ import annotations

import json

import pytest

from indepth_analysis.skills.euro_macro.monthly_brief import finalize
from indepth_analysis.skills.euro_macro.monthly_brief.edition import (
    Edition,
    load_edition,
)


def _edition(tmp_path, phase="preview"):
    ed = Edition(
        month="2026-09",
        phase=phase,
        as_of="2026-10-02",
        report_date="2026-10-05",
        root=str(tmp_path),
        ecb={"last_meeting": "2026-09-10", "next_meeting": "2026-10-29"},
    )
    ed.save()
    return ed


def test_edition_roundtrip(tmp_path):
    ed = _edition(tmp_path)
    got = load_edition(tmp_path)
    assert got.collection == "EUROPE 202609"
    assert got.window == {"from": "2026-09-01", "to": "2026-10-02"}
    assert got.prior_month_root.endswith("2026-08")
    assert got.doc_name("report") == "2026-10-05_europe_macro_preview_report.md"
    assert ed.phase_tag == "[Preview]"


def test_edition_rejects_bad_phase(tmp_path):
    with pytest.raises(ValueError):
        Edition(month="2026-09", phase="spot", as_of="x", report_date="y")


GOOD = """# [Preview] 유럽 매크로 — 2026년 9월

## 요약

▲ 유로존 물가는 에너지 주도로 2026년 8월 3.2%로 확정됨. [차트: hicp]

## 참고문헌

- ECB PREVIEW: Rate Hike in September (Bloomberg Intelligence, 2026-09-03) 정본
"""


def test_gate_pass_and_exempt_references(tmp_path):
    ed = _edition(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/chart_pack.json").write_text(
        json.dumps({"charts": [{"id": "hicp"}]})
    )
    f = tmp_path / "r.md"
    f.write_text(GOOD, encoding="utf-8")
    r = finalize.gate(ed, f, "summary", run_lints=False)
    assert r["status"] == "PASS", r["blocks"]


@pytest.mark.parametrize(
    "line",
    [
        "정본 기준 수치임.",
        "N02 리서치에 따르면 상승함.",
        "BI-12 주장과 일치함.",
        "자료가 확인되지 않아 제외함.",
        "preview 단계에서 판단함.",
        "지난달 대비 상승함.",
        "물가는 3.2%로 확인됨 [확정].",
        "[차트: missing_chart] 참조.",
    ],
)
def test_gate_blocks(tmp_path, line):
    ed = _edition(tmp_path)
    f = tmp_path / "r.md"
    f.write_text(f"# [Preview] 제목\n\n## 1. 장\n\n- {line}\n", encoding="utf-8")
    r = finalize.gate(ed, f, "summary", run_lints=False)
    assert r["status"] == "FAIL"


def test_gate_requires_phase_tag(tmp_path):
    ed = _edition(tmp_path, phase="interim")
    f = tmp_path / "r.md"
    f.write_text("# [Preview] 제목\n\n본문임.\n", encoding="utf-8")
    r = finalize.gate(ed, f, "summary", run_lints=False)
    assert any("H1" in b for b in r["blocks"])


def test_g7_not_flagged(tmp_path):
    ed = _edition(tmp_path)
    f = tmp_path / "r.md"
    f.write_text("# [Preview] 제목\n\n- G7 국채 금리 상승함.\n", encoding="utf-8")
    assert finalize.gate(ed, f, "summary", run_lints=False)["status"] == "PASS"


PENDING_DOC = """# [Preview] 제목

## 3. 물가

<!-- PENDING:ea_hicp_flash_headline_202609 -->
- **(발표 예정: 9월 HICP 속보, 10/2)** 컨센서스는 3.6%(직전 3.2%)임.
  - 상회 시: 10월 추가 인상 가능성 확대로 판단.
<!-- /PENDING:ea_hicp_flash_headline_202609 -->
"""


def test_pending_blocks_gate(tmp_path):
    ed = _edition(tmp_path)
    f = tmp_path / "r.md"
    f.write_text(PENDING_DOC, encoding="utf-8")
    draft = finalize.gate(ed, f, "summary", run_lints=False, allow_pending=True)
    assert draft["status"] == "PASS", draft["blocks"]
    assert draft["stats"]["pending"] == ["ea_hicp_flash_headline_202609"]
    final = finalize.gate(ed, f, "summary", run_lints=False)
    assert final["status"] == "FAIL"


def test_edition_pending_window(tmp_path):
    ed = Edition(
        month="2026-09",
        phase="preview",
        as_of="2026-09-30",
        report_date="2026-10-05",
        root=str(tmp_path),
        release_cutoff="2026-10-02",
    )
    assert ed.has_pending
    assert ed.pending_window == {"from": "2026-10-01", "to": "2026-10-02"}
    ed.save()
    assert load_edition(tmp_path).release_cutoff == "2026-10-02"
    plain = Edition(
        month="2026-09", phase="preview", as_of="2026-10-02", report_date="x"
    )
    assert not plain.has_pending


def test_relative_date_word_boundary(tmp_path):
    ed = _edition(tmp_path)
    f = tmp_path / "r.md"
    f.write_text("# [Preview] 제목\n\n- 첫 인상이 연내일 수 있음.\n", encoding="utf-8")
    assert finalize.gate(ed, f, "summary", run_lints=False)["status"] == "PASS"
    f.write_text("# [Preview] 제목\n\n- 내일 발표 예정임.\n", encoding="utf-8")
    assert finalize.gate(ed, f, "summary", run_lints=False)["status"] == "FAIL"
