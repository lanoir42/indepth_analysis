"""v3 리서치 프롬프트·문체 사양·커버리지·역할 파일 검증 (모델 호출 없음)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from indepth_analysis.skills.euro_macro.monthly_brief import prompts as p3
from indepth_analysis.skills.euro_macro.monthly_brief import research
from indepth_analysis.skills.euro_macro.monthly_brief.edition import (
    Edition,
    load_edition,
)

PKG = Path(p3.__file__).parent
ALL_AXES = [k.split("_", 1)[0] for k in p3.RESEARCH_AXES]
ALL_WEB = [k.split("_", 1)[0] for k in p3.WEB_SERIES]


def _edition(tmp_path: Path, phase: str = "preview") -> Edition:
    ed = Edition(
        month="2031-04",
        phase=phase,
        as_of="2031-05-02",
        report_date="2031-05-05",
        root=str(tmp_path),
        ecb={"last_meeting": "2031-04-16", "next_meeting": "2031-06-04"},
        events=[
            {
                "date": "2031-04-30",
                "geo": "EA",
                "kind": "data",
                "title": "4월 HICP 속보",
            },
            {
                "date": "2031-04-20",
                "geo": "FR",
                "kind": "politics",
                "title": "불신임 표결",
            },
        ],
    )
    ed.save()
    return ed


def _string_constants() -> list[str]:
    out = [v for v in vars(p3).values() if isinstance(v, str)]
    for spec in list(p3.RESEARCH_AXES.values()) + list(p3.WEB_SERIES.values()):
        out += [v for v in spec.values() if isinstance(v, str)]
    return out


def test_templates_have_no_hardcoded_years():
    for s in _string_constants():
        for year in ("2024", "2025", "2026", "2027"):
            assert year not in s, f"hard-coded {year}: {s[:80]}"


def test_all_twelve_axes_and_two_web_series():
    assert len(p3.RESEARCH_AXES) == 12
    assert list(p3.RESEARCH_AXES)[0] == "R01_ecb"
    assert list(p3.RESEARCH_AXES)[-1] == "R12_calendar_consensus"
    assert set(p3.WEB_SERIES) == {"W1_pmi", "W2_ois"}
    for g in p3.AXIS_GROUPS.values():
        assert set(g) <= set(p3.BI_GROUPS)


def test_prompts_use_only_edition_dates(tmp_path):
    ed = _edition(tmp_path)
    jobs = research.plan_jobs(tmp_path, ed, ALL_AXES, ALL_WEB, None)
    assert len(jobs) == 14
    for j in jobs:
        prompt = j["prompt"]
        assert "2026" not in prompt and "2025" not in prompt, j["name"]
        assert ed.as_of in prompt, j["name"]
        if j["kind"] == "axis":
            assert ed.window["from"] in prompt and ed.window["to"] in prompt
            assert "2031-06-04" in prompt  # next ECB meeting from edition
            assert "## 출처 목록" in prompt and "## 수치 레코드" in prompt
            assert "2030년" in prompt  # prev_year derived, year-confusion rule
    names = {j["name"] for j in jobs}
    assert "R06_politics_fr" in names and "W2_ois" in names


def test_politics_axes_carry_requirements(tmp_path):
    ed = _edition(tmp_path)
    for key in ("R06", "R07", "R08", "R09", "R11"):
        prompt = p3.build_axis_prompt(key, ed, "", "")
        assert "정치 축 필수 요건" in prompt
        assert "의회 구도" in prompt and "시나리오" in prompt
    assert "정치 축 필수 요건" not in p3.build_axis_prompt("R02", ed, "", "")


def test_placeholders_and_context_injection(tmp_path):
    ed = _edition(tmp_path)
    prompt = p3.build_axis_prompt("R01", ed, "", "")
    assert "facts.md 미생성" in prompt and "BI 섹션 스캐폴드 없음" in prompt
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "facts.md").write_text("- DFR 9.99% FACTMARK\n", "utf-8")
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "ECB.md").write_text(
        "# ECB\n- BI 주장 ECBMARK\n" + "x\n" * 5000 + "<!-- NARRATIVE -->\n", "utf-8"
    )
    jobs = {
        j["name"]: j for j in research.plan_jobs(tmp_path, ed, ["R01", "R06"], [], None)
    }
    r01 = jobs["R01_ecb"]["prompt"]
    assert "FACTMARK" in r01 and "ECBMARK" in r01 and "NARRATIVE" not in r01
    assert len(research.bi_context(tmp_path, ("ECB",))) < 6500
    assert "ECBMARK" not in jobs["R06_politics_fr"]["prompt"]
    assert "불신임 표결" in jobs["R06_politics_fr"]["prompt"]  # FR event filtered in


def test_gap_batches_and_phase_suffix(tmp_path):
    ed = _edition(tmp_path, phase="interim")
    gaps = tmp_path / "_work" / "gaps_r1.json"
    gaps.parent.mkdir(parents=True)
    items = [
        {"id": f"g{i}", "question": f"질문 {i}", "context": "ch06"} for i in range(8)
    ]
    gaps.write_text(json.dumps(items, ensure_ascii=False), "utf-8")
    jobs = research.plan_jobs(tmp_path, ed, ["R01"], ["W1"], gaps)
    names = [j["name"] for j in jobs]
    assert names == [
        "R01_ecb_interim",
        "W1_pmi_interim",
        "G_r1_1_interim",
        "G_r1_2_interim",
    ]
    assert jobs[0]["raw"].name == "R01_ecb_interim.md"
    assert jobs[1]["dest"].name == "web_series_W1_pmi.json"
    assert "질문 7" in jobs[3]["prompt"] and "질문 5" not in jobs[3]["prompt"]


def test_dry_run_writes_prompts_without_model(tmp_path, monkeypatch):
    _edition(tmp_path)

    async def boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("model called in dry-run")

    monkeypatch.setattr(research, "_run_claude", boom)
    res = asyncio.run(research.run_v3(tmp_path, ALL_AXES, ALL_WEB, dry_run=True))
    assert len(res) == 14 and all(v == 0 for v in res.values())
    logs = tmp_path / "_work" / "logs"
    assert (logs / "R12_calendar_consensus.prompt.txt").exists()
    assert (logs / "W2_ois.prompt.txt").exists()
    assert load_edition(tmp_path).month == "2031-04"


def test_web_series_prompt_json_template(tmp_path):
    ed = _edition(tmp_path)
    w1 = p3.build_web_series_prompt("W1", ed, "")
    assert '"series"' in w1 and "2028-01" in w1  # series_start = year-3
    assert "ea_pmi_composite" in w1
    w2 = p3.build_web_series_prompt("W2", ed, "")
    assert "2031-06-04" in w2 and "2031-04-02" in w2  # ois_prev_date = as_of-30d


# --- coverage.yaml ---------------------------------------------------------

EXPECTED_CHAPTERS = [
    "summary",
    "ch01_judgement",
    "ch02_monetary",
    "ch03_inflation",
    "ch04_growth_labour",
    "ch05_markets_credit",
    "ch06_politics",
    "ch07_external_energy",
    "ch08_uk_periphery",
    "ch09_outlook",
    "ch10_changes",
    "appendix",
]


@pytest.fixture(scope="module")
def coverage() -> dict:
    return yaml.safe_load((PKG / "coverage.yaml").read_text(encoding="utf-8"))


def test_coverage_structure(coverage):
    chapters = coverage["report"]["chapters"]
    assert [c["key"] for c in chapters] == EXPECTED_CHAPTERS
    for c in chapters:
        assert {"key", "title", "target_chars", "effort", "items"} <= set(c)
        for it in c["items"]:
            assert {"id", "description", "must_have"} <= set(it)
            assert isinstance(it["must_have"], list) and it["must_have"]
    by_key = {c["key"]: c for c in chapters}
    for k in ("ch02_monetary", "ch06_politics", "ch09_outlook"):
        assert by_key[k]["effort"] == "high"
    assert "advisor" in coverage["effort_policy"]["high"]
    assert by_key["ch10_changes"]["phases"] == ["final"]
    growth = by_key["ch04_growth_labour"]["country_subsections"]
    assert growth["countries"] == ["DE", "FR", "IT", "ES"]
    pol = by_key["ch06_politics"]["country_subsections"]
    assert pol["countries"] == ["FR", "DE", "IT", "ES", "EU", "UK"]
    assert len(pol["template"]) >= 5
    body = sum(c["target_chars"] for c in chapters if c["key"] != "ch10_changes")
    lo, hi = coverage["report"]["total_chars"]
    assert lo <= body <= hi


def test_coverage_reader_questions_and_explainer(coverage):
    rqs = coverage["reader_questions"]
    assert len(rqs) >= 15
    assert sum(1 for q in rqs if q["origin"] == "seed_user") >= 6
    report_keys = set(EXPECTED_CHAPTERS)
    ex_keys = {c["key"] for c in coverage["explainer"]["chapters"]}
    for q in rqs:
        assert q["report_chapter"] in report_keys | {None}
        assert q["explainer_chapter"] in ex_keys
    for c in coverage["explainer"]["chapters"]:
        assert c["maps_to"] in report_keys and c["topics"]
    assert coverage["explainer"]["max_overlap_with_report"] <= 0.2


# --- STYLE_BRIEF / roles ------------------------------------------------------

BANNED = [
    "정본",
    "DATAPACK",
    "datapack",
    "§",
    "팀 Noir",
    "Advisor",
    "Quant",
    "Chief",
    "Polish",
    "감사",
    "채점",
    "본 단계",
    "본 회차",
    "본 문서",
    "preview",
    "spot",
    "review",
    "interim",
    "등재",
    "[확정]",
    "[보도]",
    "[추정]",
    "[시장]",
    "[미확인]",
    r"\b[NSDRGW]\d{1,2}\b",
    r"\bBI-?\d+\b",
    r"\b[PSR]D-\d+\b",
    "확인되지 않아",
    "관측 대상에서 제외",
    "인용하지 않는다",
    "산출하지 않는다",
]


def test_style_brief_lists_banned_tokens():
    text = (PKG / "STYLE_BRIEF.md").read_text(encoding="utf-8")
    for tok in BANNED:
        assert tok in text, tok
    assert "A가 아니라 B" in text and "KCIF" in text and "[판단]" in text


ROLES = [
    "_common",
    "bi_section",
    "quant",
    "advisor",
    "chief_chapter",
    "polish",
    "explainer_chapter",
    "explainer_polish",
    "audit_fact",
    "audit_logic",
    "audit_style",
    "audit_coverage",
    "audit_reader",
    "fixer",
    "harmonizer",
    "change_review",
    "editorial",
]


def test_role_files_present():
    for r in ROLES:
        f = PKG / "roles" / f"{r}.md"
        assert f.exists(), r
        text = f.read_text(encoding="utf-8")
        assert "2026-0" not in text.replace("2026-09-09_37495", "")
    for r in ROLES:
        if r.startswith("audit_"):
            text = (PKG / "roles" / f"{r}.md").read_text(encoding="utf-8")
            assert '"verdict": "PASS|FAIL"' in text and "gap_question" in text
