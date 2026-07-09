"""Institution forecast comparison tables (routinized).

Renders verified institution-forecast data (assembled by the research/QA pipeline)
into Notion-safe comparison tables:
  A. Euro-area GDP + inflation forecasts, prior vintage vs latest vintage.
  B. ECB policy-rate (DFR) path by institution across 26Q3/26Q4/27H1/27H2,
     prior-snapshot view vs latest-snapshot view.

Design principle (anti-hallucination): the renderer NEVER invents values. Every
cell comes from the input JSON, and any missing value is rendered as "미확인" so
gaps are visible rather than silently filled. Full source URLs + dates live in a
dedicated 출처 목록 table so every number is traceable.

Input JSON schema (all forecast entries carry {value/…, date, source, url}):

    {
      "meta": {
        "title": str, "as_of": "YYYY-MM-DD", "region": str,
        "vintage_prior_label": str, "vintage_latest_label": str,
        "rate_prior_label": str, "rate_latest_label": str
      },
      "gdp_2026":      [ {"institution","group","prior":ENTRY,"latest":ENTRY}, … ],
      "inflation_2026":[ {"institution","group","prior":ENTRY,"latest":ENTRY}, … ],
      "rate_dfr":      [ {"institution","group","prior":RATE,"latest":RATE}, … ],
      "sources":       [ {"id","label","url"} ],   # optional extra sources
      "notes":         str                          # optional methodology note
    }
  where ENTRY = {"value": float|None, "date": "YYYY-MM-DD"|None,
                 "source": str|None, "url": str|None}
        RATE  = {"26Q3","26Q4","27H1","27H2": float|None,
                 "date","source","url"}
"""

from __future__ import annotations

import json
from pathlib import Path

RATE_HORIZONS = ["26Q3", "26Q4", "27H1", "27H2"]


# --------------------------------------------------------------------------
# formatting helpers
# --------------------------------------------------------------------------
def _short_date(d: str | None) -> str:
    """'2026-04-17' -> '26-04'; None/malformed -> ''."""
    if not d or not isinstance(d, str) or len(d) < 7:
        return ""
    parts = d.split("-")
    if len(parts) < 2:
        return ""
    return f"{parts[0][2:]}-{parts[1]}"


def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _val_cell(entry: dict | None, unit: str = "%") -> str:
    """Render a GDP/inflation value cell as '1.2% (25-10)' or '미확인'."""
    if not entry:
        return "미확인"
    v = _num(entry.get("value"))
    if v is None:
        return "미확인"
    d = _short_date(entry.get("date"))
    tail = f" ({d})" if d else ""
    return f"{v:g}{unit}{tail}"


def _delta_cell(prior: dict | None, latest: dict | None) -> str:
    """Signed change in percentage points when both ends are numeric."""
    p = _num((prior or {}).get("value"))
    la = _num((latest or {}).get("value"))
    if p is None or la is None:
        return "—"
    return f"{la - p:+.1f}%p"


def _rate_cell(rate: dict | None, horizon: str) -> str:
    if not rate:
        return "미확인"
    v = _num(rate.get(horizon))
    return f"{v:g}%" if v is not None else "미확인"


def _esc(text: str) -> str:
    """Escape pipe characters so table cells never break."""
    return str(text).replace("|", "\\|")


def _link(label: str | None, url: str | None) -> str:
    """Markdown link cell, or plain escaped label when no URL."""
    lbl = _esc(label or "링크")
    return f"[{lbl}]({url})" if url else _esc(label or "")


# --------------------------------------------------------------------------
# individual table renderers
# --------------------------------------------------------------------------
def render_metric_table(
    rows: list[dict], meta: dict, *, unit: str = "%"
) -> str:
    """One comparison table: 기관 | 지난연말 | 최근 | 변화 | 그룹."""
    prior_lbl = meta.get("vintage_prior_label", "지난 연말")
    latest_lbl = meta.get("vintage_latest_label", "최근")
    out = [
        f"| 기관 | {prior_lbl} | {latest_lbl} | 변화 | 구분 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| {_esc(r.get('institution', '?'))} "
            f"| {_val_cell(r.get('prior'), unit)} "
            f"| {_val_cell(r.get('latest'), unit)} "
            f"| {_delta_cell(r.get('prior'), r.get('latest'))} "
            f"| {_esc(r.get('group', ''))} |"
        )
    return "\n".join(out)


def render_rate_table(rows: list[dict], snapshot: str, label: str) -> str:
    """Rate-path table for one snapshot: 기관 | 26Q3 | 26Q4 | 27H1 | 27H2."""
    out = [
        f"**{label}**",
        "",
        "| 기관 | 26Q3 | 26Q4 | 27H1 | 27H2 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        rate = r.get(snapshot)
        cells = " | ".join(_rate_cell(rate, h) for h in RATE_HORIZONS)
        out.append(f"| {_esc(r.get('institution', '?'))} | {cells} |")
    return "\n".join(out)


def _collect_sources(data: dict) -> list[dict]:
    """Flatten every entry's (institution, metric, vintage, date, url)."""
    seen: set[tuple] = set()
    rows: list[dict] = []

    def add(inst, metric, vintage, entry):
        if not entry:
            return
        url = entry.get("url")
        date = entry.get("date")
        src = entry.get("source") or ""
        if not url and not src:
            return
        key = (inst, metric, vintage, url)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {"inst": inst, "metric": metric, "vintage": vintage,
             "date": date or "", "source": src, "url": url or ""}
        )

    for r in data.get("gdp_2026", []):
        add(r.get("institution"), "GDP 2026", "지난연말", r.get("prior"))
        add(r.get("institution"), "GDP 2026", "최근", r.get("latest"))
    for r in data.get("inflation_2026", []):
        add(r.get("institution"), "물가 2026", "지난연말", r.get("prior"))
        add(r.get("institution"), "물가 2026", "최근", r.get("latest"))
    for r in data.get("rate_dfr", []):
        add(r.get("institution"), "DFR 경로", "지난연말", r.get("prior"))
        add(r.get("institution"), "DFR 경로", "2026-06", r.get("latest"))
    return rows


def render_source_table(data: dict) -> str:
    rows = _collect_sources(data)
    if not rows:
        return ""
    out = ["| 기관 | 지표 | 시점 | 발표/관측일 | 출처 |", "|---|---|---|---|---|"]
    for r in rows:
        link = _link(r["source"], r["url"])
        out.append(
            f"| {_esc(r['inst'])} | {r['metric']} | {r['vintage']} "
            f"| {r['date']} | {link} |"
        )
    for s in data.get("sources", []):
        link = _link(s.get("label"), s.get("url"))
        out.append(f"| {_esc(s.get('label', ''))} | 참고 | — | — | {link} |")
    return "\n".join(out)


# --------------------------------------------------------------------------
# full appendix
# --------------------------------------------------------------------------
def render_forecast_appendix(data: dict) -> str:
    meta = data.get("meta", {})
    title = meta.get("title", "기관별 전망 비교")
    region = meta.get("region", "유로존(EA20)")
    as_of = meta.get("as_of", "")
    parts: list[str] = []
    parts.append(f"# {title}")
    parts.append("")
    parts.append(
        f"**대상:** {region} · **as-of:** {as_of} · 모든 수치는 아래 "
        "출처 목록의 발표·관측일에 대응하며, 공개 출처로 확인되지 않은 값은 "
        "**미확인**으로 표기(추정·보간 없음). 미래 값은 전망·시장기대."
    )
    parts.append("")

    gdp = data.get("gdp_2026", [])
    if gdp:
        parts.append(f"## A-1. {region} 2026년 실질 GDP 성장률 전망 (기관별)")
        parts.append("")
        parts.append(render_metric_table(gdp, meta))
        parts.append("")

    infl = data.get("inflation_2026", [])
    if infl:
        parts.append(f"## A-2. {region} 2026년 물가(HICP) 전망 (기관별)")
        parts.append("")
        parts.append(render_metric_table(infl, meta))
        parts.append("")

    rate = data.get("rate_dfr", [])
    if rate:
        parts.append("## B. ECB 정책금리(DFR) 경로 전망 (기관별)")
        parts.append("")
        parts.append(
            "두 시점의 전망을 나란히 비교한다. 2026-06-11 ECB의 2023년래 첫 "
            "인상(DFR 2.00%→2.25%)이 레짐 전환점이므로 두 시점 경로가 다르다."
        )
        parts.append("")
        parts.append(
            render_rate_table(
                rate, "prior",
                meta.get("rate_prior_label", "B-1. 지난 연말 시점 전망 (2025-12)"),
            )
        )
        parts.append("")
        parts.append(
            render_rate_table(
                rate, "latest",
                meta.get("rate_latest_label", "B-2. 2026년 6월 시점 전망"),
            )
        )
        parts.append("")

    src = render_source_table(data)
    if src:
        parts.append("## 출처 목록")
        parts.append("")
        parts.append(src)
        parts.append("")

    notes = data.get("notes")
    if notes:
        parts.append("## 방법론·주석")
        parts.append("")
        parts.append(notes)
        parts.append("")

    return "\n".join(parts).strip() + "\n"


def validate(data: dict) -> list[str]:
    """Return a list of schema problems (empty = OK)."""
    problems: list[str] = []
    if "meta" not in data:
        problems.append("meta 누락")
    if not any(data.get(k) for k in ("gdp_2026", "inflation_2026", "rate_dfr")):
        problems.append("표 데이터(gdp_2026/inflation_2026/rate_dfr) 전무")
    for r in data.get("rate_dfr", []):
        for snap in ("prior", "latest"):
            rate = r.get(snap)
            if rate and any(
                h not in rate for h in RATE_HORIZONS
            ):
                problems.append(
                    f"rate_dfr[{r.get('institution')}].{snap} 지평 누락"
                )
    return problems


def build_from_json(json_path: str | Path, out_md_path: str | Path) -> Path:
    """Load a forecast JSON, render the appendix markdown, write it out."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    md = render_forecast_appendix(data)
    out = Path(out_md_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return out
