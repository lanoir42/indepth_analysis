"""v3 결정론 데이터 계층(WP2) 테스트 — 네트워크 없이 고정 픽스처만 사용."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from indepth_analysis.skills.euro_macro.monthly_brief import (
    chart_pack,
    table_pack,
    validate_pack,
)
from indepth_analysis.skills.euro_macro.monthly_brief.datastore import (
    ecb,
    eurostat,
    store,
)
from indepth_analysis.skills.euro_macro.monthly_brief.datastore.registry import (
    SERIES,
    SeriesSpec,
)

FIX = Path(__file__).parent / "fixtures" / "monthly_brief_v3"


# ---------------------------------------------------------------------------
# 파서
# ---------------------------------------------------------------------------
def _fpd() -> dict:
    return json.loads((FIX / "eurostat_prc_hicp_fpd.json").read_text("utf-8"))


def test_parse_jsonstat_row_major_and_flags():
    rows = eurostat.parse_jsonstat(_fpd())
    assert len(rows) == 6
    got = {(r["release"], r["time"]): (r["value"], r["flag"]) for r in rows}
    assert got[("FIN", "2026-08")] == (3.2, "")
    assert got[("FLS", "2026-08")] == (3.3, "e")
    assert got[("FIN", "2026-06")] == (2.8, "")


def test_parse_jsonstat_keeps_missing_cells():
    j = _fpd()
    j["value"].pop("2")  # FIN 2026-08 제거
    rows = eurostat.parse_jsonstat(j)
    cell = next(r for r in rows if r["release"] == "FIN" and r["time"] == "2026-08")
    assert cell["value"] is None


def test_hicp_flash_appends_and_relabels():
    j = _fpd()
    j["value"].pop("2")  # 확정 8월 미발표 상황
    rows = eurostat.parse_jsonstat(j)
    pts = [["2026-06", 2.8, "final"], ["2026-07", 2.9, "final"]]
    assert eurostat.apply_hicp_flash(pts, rows) == 1
    assert pts[-1] == ["2026-08", 3.3, "flash"]
    # minr에 이미 들어온 달이라도 확정치가 없으면 flash
    pts2 = [["2026-07", 2.9, "final"], ["2026-08", 3.3, "final"]]
    eurostat.apply_hicp_flash(pts2, rows)
    assert pts2[-1][2] == "flash"


class _FakeCtx:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, base, params, cache_ns):
        return self.payload

    @staticmethod
    def url(base, params):
        return base


def test_eurostat_fetch_picks_geo_with_latest_data():
    j = {
        "id": ["geo", "time"],
        "size": [2, 3],
        "dimension": {
            "geo": {"category": {"index": {"EA": 0, "EA21": 1}}},
            "time": {"category": {"index": {"2026-05": 0, "2026-06": 1, "2026-07": 2}}},
        },
        "value": {"0": 1.0, "3": 1.1, "4": 1.2, "5": 1.3},
        "status": {"5": "p"},
    }
    spec = SeriesSpec(
        "x",
        "t",
        "%",
        "M",
        "EA",
        "c",
        "eurostat",
        {"dataset": "d", "filters": {}, "geo_candidates": ["EA", "EA21"]},
    )
    res = eurostat.fetch(spec, _FakeCtx(j))
    assert res["meta"]["geo_code"] == "EA21"
    assert res["points"][-1] == ["2026-07", 1.3, "prelim"]


def test_parse_sdmx_csv_ecb_and_bbk():
    rows = ecb.parse_sdmx_csv((FIX / "ecb_exr_krw.csv").read_text("utf-8"))
    assert rows and all(r[1] is not None for r in rows)
    assert rows[0][0].startswith("2023-01")
    bb = ecb.parse_sdmx_csv((FIX / "bbk_bund10y.csv").read_text("utf-8"))
    assert bb[0] == ("2024-01-01", None, "") or bb[0][1] is None  # 휴일 '.'
    assert bb[1][0] == "2024-01-02" and bb[1][1] == pytest.approx(2.14)


# ---------------------------------------------------------------------------
# 격자·결측
# ---------------------------------------------------------------------------
def test_fill_gaps_inserts_null_not_interpolation():
    pts = [["2026-01", 1.0, "final"], ["2026-03", 3.0, "final"]]
    out = store.fill_gaps("M", pts)
    assert [p[0] for p in out] == ["2026-01", "2026-02", "2026-03"]
    assert out[1][1] is None
    q = store.fill_gaps("Q", [["2025-Q3", 1, "final"], ["2026-Q1", 2, "final"]])
    assert [p[0] for p in q] == ["2025-Q3", "2025-Q4", "2026-Q1"]


def _rec(freq, pts, concept, tier="api", unit="%"):
    return {
        "title_ko": concept,
        "unit": unit,
        "freq": freq,
        "geo": "EA",
        "concept": concept,
        "tier": tier,
        "source": "Test",
        "dataset": "ds",
        "url": "",
        "fetched": "2026-09-30T00:00:00+00:00",
        "points": pts,
        "last_period": next((p[0] for p in reversed(pts) if p[1] is not None), None),
        "decimals": 1,
        "role": "primary",
    }


def _mini_store():
    a = [[f"2025-{m:02d}", 2.0 + m / 10, "final"] for m in range(1, 13)]
    a[4][1] = None  # 5월 결측
    b = [[f"2025-{m:02d}", 1.0, "final"] for m in range(1, 10)]  # 9월까지
    return {
        "as_of": "2026-01-15",
        "series": {
            "a": _rec("M", a, "ca"),
            "b": _rec("M", b, "cb"),
            "d": _rec(
                "D",
                [["2025-12-30", 1.10, "spot"], ["2026-01-02", 1.12, "spot"]],
                "cd",
                tier="market",
            ),
        },
        "errors": {},
    }


def _chart(**kw):
    base = dict(
        id="t1",
        section="inflation",
        order=1,
        kind="line",
        freq="M",
        series=[chart_pack.S("a", "A"), chart_pack.S("b", "B", "secondary")],
        title=lambda c: f"A {c.f('a')}% ({c.pko('a')})",
        subtitle=lambda c: f"B {c.f('b')}%",
        y=[chart_pack.Y("%", 1)],
    )
    base.update(kw)
    return chart_pack.Chart(**base)


def _monthly_window(monkeypatch):
    monkeypatch.setattr(chart_pack, "_window", lambda ch, as_of: ("2025-01", None))


def test_grid_alignment_with_nulls(monkeypatch, tmp_path):
    _monthly_window(monkeypatch)
    st = _mini_store()
    c = chart_pack.build_chart(_chart(), st, st["as_of"], "2025-12")
    labels = c["x"]["labels"]
    assert labels == [f"2025-{m:02d}" for m in range(1, 13)]  # 라벨 삭제 없음
    a, b = c["series"]
    assert a["values"][4] is None and a["status"][4] is None
    assert b["values"][9:] == [None, None, None]
    assert b["last_period"] == "2025-09"
    assert c["title"] == "A 3.2% (2025년 12월)"
    p = tmp_path / "c.csv"
    chart_pack.write_csv(c, p)
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    assert len(rows) == 12 * 2
    assert rows[0].keys() == set(chart_pack.CSV_HEADER)


def test_monthly_avg_marks_partial_month_prelim():
    pts = [
        ["2026-08-31", 1.0, "spot"],
        ["2026-09-01", 2.0, "spot"],
        ["2026-09-15", 4.0, "spot"],
    ]
    out = chart_pack.monthly_avg(pts, "2026-09-20")
    assert out == [["2026-08", 1.0, "final"], ["2026-09", 3.0, "prelim"]]


def test_decision_dates_table_and_derived_rule():
    s = {
        "series": {
            "ecb_dfr_changes": {
                "points": [["2025-06-11", 2.0, "final"], ["2026-09-16", 2.5, "final"]]
            },
            "ecb_mro_changes": {"points": [["2025-06-11", 2.15, "final"]]},
            "ecb_mlf_changes": {"points": []},
        }
    }
    d = chart_pack.decision_dates(s)
    assert d[0]["decision"] == "2025-06-05" and d[0]["decision_basis"] == "table"
    assert d[1]["decision"] == "2026-09-10" and d[1]["decision_basis"] == "derived"
    assert d[1]["dfr_chg_bp"] == 50 and d[1]["mro"] == 2.15


# ---------------------------------------------------------------------------
# 검증기
# ---------------------------------------------------------------------------
def _write_pack(root: Path, st: dict, charts: list[dict], tables=None):
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "series_store.json").write_text(json.dumps(st), "utf-8")
    for c in charts:
        chart_pack.write_csv(c, root / c["data_csv"])
    (root / "data" / "chart_pack.json").write_text(
        json.dumps({"charts": charts, "skipped": []}), "utf-8"
    )
    (root / "data" / "table_pack.json").write_text(
        json.dumps({"tables": tables or []}), "utf-8"
    )


def _rules(doc, level="FAIL"):
    return {i["rule"] for i in doc["items"] if i["level"] == level}


def test_validator_passes_clean_chart(monkeypatch, tmp_path):
    _monthly_window(monkeypatch)
    st = _mini_store()
    st["as_of"] = "2026-01-15"
    c = chart_pack.build_chart(_chart(), st, st["as_of"], "2025-12")
    _write_pack(tmp_path, st, [c])
    doc = validate_pack.validate(tmp_path)
    assert not _rules(doc), doc["items"]


def test_validator_flags_freq_mix_dropped_label_and_title(monkeypatch, tmp_path):
    _monthly_window(monkeypatch)
    st = _mini_store()
    good = chart_pack.build_chart(_chart(), st, st["as_of"], "2025-12")
    mixed = json.loads(json.dumps(good))
    mixed["id"], mixed["data_csv"] = "mixed", "data/charts/mixed.csv"
    mixed["series"][1]["freq"] = "D"
    dropped = json.loads(json.dumps(good))
    dropped["id"], dropped["data_csv"] = "dropped", "data/charts/dropped.csv"
    del dropped["x"]["labels"][4]
    for s in dropped["series"]:
        del s["values"][4]
        del s["status"][4]
    wrong_title = json.loads(json.dumps(good))
    wrong_title["id"], wrong_title["data_csv"] = "wt", "data/charts/wt.csv"
    wrong_title["title"] = "A 3.3% (2025년 12월)"
    _write_pack(tmp_path, st, [mixed, dropped, wrong_title])
    doc = validate_pack.validate(tmp_path)
    fails = {(i["rule"], i["target"]) for i in doc["items"] if i["level"] == "FAIL"}
    assert ("C2", "mixed") in fails
    assert ("C3", "dropped") in fails
    assert ("C7", "wt") in fails
    assert doc["status"] == "FAIL"


def test_title_numbers_ignores_dates_and_identifiers():
    toks = validate_pack.title_numbers(
        "EUR/KRW 1,536.74 · 9월 29일 · G47 · Brent $96.33 · 스프레드 82bp · +0.6%"
    )
    assert toks == ["1536.74", "96.33", "82", "0.6"]


def test_llm_web_headline_warns_and_xcheck(monkeypatch, tmp_path):
    _monthly_window(monkeypatch)
    st = _mini_store()
    st["series"]["a"]["tier"] = "llm_web"
    st["series"]["x"] = {
        **_rec("M", [["2025-12", 9.9, "final"]], "xc_a"),
        "role": "xcheck",
        "xcheck_of": "ca",
    }
    c = chart_pack.build_chart(_chart(headline=True), st, st["as_of"], "2025-12")
    _write_pack(tmp_path, st, [c])
    doc = validate_pack.validate(tmp_path)
    assert {"C10", "C11"} <= _rules(doc, "WARN")


def test_freshness_warn(monkeypatch, tmp_path):
    _monthly_window(monkeypatch)
    st = _mini_store()
    st["as_of"] = "2026-06-30"  # b(2025-09)는 9개월 지연
    c = chart_pack.build_chart(_chart(), st, st["as_of"], "2026-06")
    _write_pack(tmp_path, st, [c])
    doc = validate_pack.validate(tmp_path)
    assert "C8" in _rules(doc, "WARN")


def test_duplicate_concept_fails(tmp_path):
    st = _mini_store()
    st["series"]["b"]["concept"] = "ca"
    _write_pack(tmp_path, st, [])
    doc = validate_pack.validate(tmp_path)
    assert "S3" in _rules(doc)


# ---------------------------------------------------------------------------
# 표
# ---------------------------------------------------------------------------
def test_key_indicator_change_is_code_computed_and_checked():
    st = {
        "as_of": "2026-10-02",
        "series": {
            "ea_hicp_headline": _rec(
                "M",
                [["2026-07", 2.9, "final"], ["2026-08", 3.3, "flash"]],
                "hicp_headline_yoy",
            )
        },
        "calendar": {"next_releases": {"EU.HICP_YOY": "2026-10-31"}},
    }
    t = table_pack.t_key_indicators(st)
    row = t["rows"][0]
    assert row["change"] == pytest.approx(0.4)
    assert row["status"] == "속보" and row["next_release"] == "2026-10-31"
    rep = validate_pack.Report()
    validate_pack.check_table(t, rep)
    assert not rep.items
    row["change"] = 0.3  # 수기 오기 → 재계산 불일치
    validate_pack.check_table(t, rep)
    assert [i["rule"] for i in rep.items] == ["T1"]


def test_recalc_ops():
    assert validate_pack._recalc("diff_bp", 2.5, 2.25) == pytest.approx(25)
    assert validate_pack._recalc("pct", 110, 100) == pytest.approx(10)
    assert validate_pack._recalc("auto", 1.1, 1.0, "bp") == pytest.approx(10)
    assert validate_pack._recalc("diff", None, 1) is None


def test_to_markdown_formats_signed_and_missing():
    t = {
        "title": "T",
        "subtitle": "",
        "columns": [
            table_pack.col("k", "항목", bold=True),
            table_pack.col("v", "값", "%", 1, signed=True),
        ],
        "rows": [{"k": "a", "v": 0.25}, {"k": "b", "v": None}],
        "sources": ["S"],
        "footnote": "",
    }
    md = table_pack.to_markdown(t)
    assert "| **a** | +0.2 |" in md or "| **a** | +0.3 |" in md
    assert "| **b** | – |" in md


def test_registry_ids_unique_and_primary_concepts_unique():
    ids = [s.id for s in SERIES]
    assert len(ids) == len(set(ids))
    concepts = [s.concept for s in SERIES if s.role == "primary"]
    assert len(concepts) == len(set(concepts))
    assert len(SERIES) >= 45


def test_store_ingests_web_series_as_llm_web(tmp_path):
    (tmp_path / "data").mkdir()
    web = {
        "as_of": "2026-10-02",
        "series": {
            "ea_pmi_composite": {
                "title": "EA composite",
                "unit": "index",
                "frequency": "M",
                "x_labels": ["2026-07", "2026-8", "2026-09"],
                "data": [50.9, None, 51.2],
                "source": "S&P Global",
                "url": "https://example.org",
                "published": "2026-09-23",
                "note": "9월 flash",
            },
            "bad": {"x_labels": ["2026-01"], "data": [1, 2]},
        },
    }
    (tmp_path / "data" / "web_series_W1_pmi.json").write_text(
        json.dumps(web), "utf-8"
    )
    doc = store.build(tmp_path, "2026-10-02", offline=True, specs=[])
    s = doc["series"]["ea_pmi_composite"]
    assert s["tier"] == "llm_web" and s["concept"] == "pmi_composite_ea"
    assert s["points"] == [
        ["2026-07", 50.9, "final"],
        ["2026-08", None, "final"],
        ["2026-09", 51.2, "flash"],
    ]
    assert "bad" in doc["errors"]
