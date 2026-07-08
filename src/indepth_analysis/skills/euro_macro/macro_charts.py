"""Macro chart + PowerPoint deck builder for Euro Macro monthly updates.

The stock ``slide_renderer`` produces a text-only dashboard. This module adds
real data-driven charts (matplotlib PNGs) and assembles them into a PPTX deck,
driven by a chart-ready JSON appendix so every chart is traceable to a series.

Chart labels are in English on purpose (guaranteed glyph coverage); the report
body remains Korean.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger(__name__)

# Distinct, print-friendly palette.
_PALETTE = [
    "#1b3a5c",
    "#d62728",
    "#2ca02c",
    "#ff7f0e",
    "#9467bd",
    "#17becf",
    "#8c564b",
]


def _fig(path: Path, fig) -> Path:
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _style(ax) -> None:
    ax.set_facecolor("white")
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.tick_params(labelsize=9)


# --------------------------------------------------------------------------
# Chart dataset construction (chart-ready JSON appendix)
# --------------------------------------------------------------------------
def _group_eurostat(df, cols: list[str]) -> list[dict]:
    """Group a tidy Eurostat frame into per-entity {meta, values[]} records."""
    if df is None or getattr(df, "empty", True) or "value" not in df.columns:
        return []
    if "time" not in df.columns:
        return []
    present = [c for c in cols if c in df.columns]
    out: list[dict] = []
    for keys, g in df.groupby(present):
        keys = keys if isinstance(keys, tuple) else (keys,)
        meta = dict(zip(present, keys))
        for c in present:
            lbl = f"{c}_label"
            if lbl in g.columns:
                meta[lbl] = str(g[lbl].iloc[0])
        g2 = g.sort_values("time")
        vals = [
            {"period": str(t), "value": round(float(v), 4)}
            for t, v in zip(g2["time"], g2["value"])
            if v == v  # drop NaN
        ]
        if vals:
            out.append({**meta, "values": vals})
    return out


def build_live_dataset(
    *,
    start_month: str = "2024-01",
    start_quarter: str = "2024-Q1",
    curated: dict | None = None,
) -> dict:
    """Build a chart-ready dataset from LIVE structured feeds (no data.json needed).

    Self-contained: fetches Eurostat GDP/unemployment/HICP + energy/index/FX via
    the keyless clients, so ``report euro-macro --slide`` can emit charts on its
    own. Note: the structured HICP and ECB-rate feeds lag; for point-in-time
    accuracy pass a ``curated`` block sourced from web research.
    """
    from indepth_analysis.data.energy_client import EnergyClient
    from indepth_analysis.data.eurostat_client import (
        COICOP_ALL,
        GDP_UNIT_QOQ,
        GDP_UNIT_YOY,
        GEO_DE,
        GEO_EA20,
        GEO_ES,
        GEO_EU27,
        GEO_FR,
        GEO_IT,
        EurostatClient,
    )

    geos = [GEO_EA20, GEO_EU27, GEO_DE, GEO_FR, GEO_IT, GEO_ES]
    es = EurostatClient()
    try:
        gdp_q = _group_eurostat(
            es.get_gdp(geos=geos, start_period=start_quarter, unit=GDP_UNIT_QOQ),
            ["geo"],
        )
        gdp_y = _group_eurostat(
            es.get_gdp(geos=geos, start_period=start_quarter, unit=GDP_UNIT_YOY),
            ["geo"],
        )
        unemp = _group_eurostat(
            es.get_unemployment(geos=geos, start_period=start_month), ["geo"]
        )
        hicp = _group_eurostat(
            es.get_hicp(
                geos=geos, coicops=[COICOP_ALL], start_period=start_month, rate=True
            ),
            ["geo", "coicop"],
        )
    finally:
        es.close()

    try:
        market = EnergyClient().fetch_all(period="1y")
    except Exception as e:  # noqa: BLE001
        logger.warning("market fetch failed: %s", e)
        market = {"energy": [], "indices": [], "fx": [], "ai_basket": []}

    dataset = {
        "meta": {"source": "live Eurostat + yfinance"},
        "gdp_qoq_pct": {
            "unit": "% QoQ",
            "source": "Eurostat namq_10_gdp",
            "series": gdp_q,
        },
        "gdp_yoy_pct": {
            "unit": "% YoY",
            "source": "Eurostat namq_10_gdp",
            "series": gdp_y,
        },
        "unemployment_pct": {
            "unit": "% labour force",
            "source": "Eurostat une_rt_m",
            "series": unemp,
        },
        "hicp_yoy_pct": {
            "unit": "% YoY (headline)",
            "source": "Eurostat prc_hicp_manr (feed lags)",
            "series": hicp,
        },
        "energy": {
            "unit": "level",
            "source": "yfinance",
            "series": market.get("energy", []),
        },
        "indices": {
            "unit": "index",
            "source": "yfinance",
            "series": market.get("indices", []),
        },
        "fx": {"unit": "rate", "source": "yfinance", "series": market.get("fx", [])},
        "ai_basket": {
            "unit": "index (rebased=100)",
            "source": "yfinance",
            "series": market.get("ai_basket", []),
        },
    }
    if curated:
        dataset["curated"] = curated
    return dataset


def build_chart_dataset(
    data_json_path: Path,
    *,
    curated: dict | None = None,
    refresh_market: bool = True,
) -> dict:
    """Build a compact, chart-ready dataset from the verified data.json backbone.

    Optionally refreshes market series (energy/indices/fx) to today's close and
    merges a ``curated`` block (series sourced from the web-research findings,
    e.g. the ECB policy-rate path and the H1-2026 HICP reacceleration, which the
    structured feeds lag). Every entry keeps its source tag.
    """
    data = json.loads(Path(data_json_path).read_text(encoding="utf-8"))
    es_block = data.get("eurostat", {})

    def _euro(block_key: str) -> list[dict]:
        blk = es_block.get(block_key, {})
        return blk.get("series", [])

    market = data.get("market", {})
    if refresh_market:
        try:
            from indepth_analysis.data.energy_client import EnergyClient

            market = EnergyClient().fetch_all(period="1y")
        except Exception as e:  # noqa: BLE001
            logger.warning("market refresh failed, using backbone: %s", e)

    dataset = {
        "meta": {
            "source": "data.json backbone (Eurostat/ECB/yfinance) + curated findings",
            "as_of": data.get("meta", {}).get("as_of"),
        },
        "gdp_qoq_pct": {
            "unit": "% QoQ",
            "source": "Eurostat namq_10_gdp",
            "series": _euro("gdp_qoq_pct"),
        },
        "gdp_yoy_pct": {
            "unit": "% YoY",
            "source": "Eurostat namq_10_gdp",
            "series": _euro("gdp_yoy_pct"),
        },
        "unemployment_pct": {
            "unit": "% labour force",
            "source": "Eurostat une_rt_m",
            "series": _euro("unemployment_pct"),
        },
        "hicp_yoy_pct": {
            "unit": "% YoY (headline)",
            "source": "Eurostat prc_hicp_manr (structured feed lags to 2025-12)",
            "series": [s for s in _euro("hicp_yoy_pct") if s.get("coicop") == "CP00"],
        },
        "energy": {
            "unit": "level",
            "source": "yfinance",
            "series": market.get("energy", []),
        },
        "indices": {
            "unit": "index (rebased=100)",
            "source": "yfinance",
            "series": market.get("indices", []),
        },
        "fx": {"unit": "rate", "source": "yfinance", "series": market.get("fx", [])},
        "ai_basket": {
            "unit": "index (rebased=100)",
            "source": "yfinance",
            "series": market.get("ai_basket", []),
        },
        "consensus": data.get("consensus", {}),
    }
    if curated:
        dataset["curated"] = curated
    return dataset


# --------------------------------------------------------------------------
# Individual chart renderers
# --------------------------------------------------------------------------
def _geo_label(s: dict) -> str:
    return s.get("geo_label") or s.get("geo") or s.get("label") or s.get("name") or "?"


def chart_energy(dataset: dict, out: Path) -> Path | None:
    series = dataset["energy"]["series"]
    plotted = [s for s in series if s.get("values")]
    if not plotted:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, s in enumerate(plotted):
        xs = [v["period"] for v in s["values"]]
        ys = [v["value"] for v in s["values"]]
        ax.plot(
            xs,
            ys,
            marker="o",
            ms=3,
            color=_PALETTE[i % len(_PALETTE)],
            label=f"{s.get('label', s.get('name'))}",
        )
    ax.set_title(
        "Energy & commodity prices (last 12m, month-end)",
        fontsize=13,
        fontweight="bold",
    )
    ax.set_ylabel("Price (USD/bbl, EUR/MWh, USD/MMBtu)")
    ax.legend(fontsize=8)
    _style(ax)
    fig.autofmt_xdate(rotation=45)
    return _fig(out / "01_energy.png", fig)


def chart_indices(dataset: dict, out: Path) -> Path | None:
    series = [s for s in dataset["indices"]["series"] if s.get("values")]
    if not series:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, s in enumerate(series):
        vals = s["values"]
        base = vals[0]["value"]
        if not base:
            continue
        xs = [v["period"] for v in vals]
        ys = [100 * v["value"] / base for v in vals]
        ax.plot(
            xs,
            ys,
            marker="o",
            ms=3,
            color=_PALETTE[i % len(_PALETTE)],
            label=s.get("label", s.get("name")),
        )
    ax.axhline(100, color="black", lw=0.6, alpha=0.5)
    ax.set_title(
        "European equity indices — rebased to 100 (last 12m)",
        fontsize=13,
        fontweight="bold",
    )
    ax.set_ylabel("Index (start = 100)")
    ax.legend(fontsize=8)
    _style(ax)
    fig.autofmt_xdate(rotation=45)
    return _fig(out / "02_indices.png", fig)


def chart_fx(dataset: dict, out: Path) -> Path | None:
    series = [s for s in dataset["fx"]["series"] if s.get("values")]
    if not series:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, s in enumerate(series):
        vals = s["values"]
        base = vals[0]["value"]
        xs = [v["period"] for v in vals]
        ys = [100 * v["value"] / base for v in vals]
        ax.plot(
            xs,
            ys,
            marker="o",
            ms=3,
            color=_PALETTE[i % len(_PALETTE)],
            label=s.get("label", s.get("name")),
        )
    ax.axhline(100, color="black", lw=0.6, alpha=0.5)
    ax.set_title(
        "EUR crosses — rebased to 100 (last 12m)", fontsize=13, fontweight="bold"
    )
    ax.set_ylabel("Rate (start = 100)")
    ax.legend(fontsize=8)
    _style(ax)
    fig.autofmt_xdate(rotation=45)
    return _fig(out / "03_fx.png", fig)


def chart_gdp_qoq(dataset: dict, out: Path) -> Path | None:
    series = [s for s in dataset["gdp_qoq_pct"]["series"] if s.get("values")]
    if not series:
        return None
    # union of periods (sorted), plot grouped lines
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, s in enumerate(series):
        xs = [v["period"] for v in s["values"]]
        ys = [v["value"] for v in s["values"]]
        ax.plot(
            xs,
            ys,
            marker="o",
            ms=4,
            color=_PALETTE[i % len(_PALETTE)],
            label=_geo_label(s),
        )
    ax.axhline(0, color="black", lw=0.6, alpha=0.6)
    ax.set_title(
        "Real GDP growth, QoQ % (Eurostat, SCA)", fontsize=13, fontweight="bold"
    )
    ax.set_ylabel("% QoQ")
    ax.legend(fontsize=8)
    _style(ax)
    fig.autofmt_xdate(rotation=45)
    return _fig(out / "04_gdp_qoq.png", fig)


def chart_gdp_yoy_latest(dataset: dict, out: Path) -> Path | None:
    series = [s for s in dataset["gdp_yoy_pct"]["series"] if s.get("values")]
    if not series:
        return None
    labels, vals = [], []
    for s in series:
        last = s["values"][-1]
        labels.append(_geo_label(s))
        vals.append(last["value"])
    period = series[0]["values"][-1]["period"]
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    labels = [labels[i] for i in order]
    vals = [vals[i] for i in order]
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#d62728" if v < 0 else "#2ca02c" for v in vals]
    ax.barh(labels, vals, color=colors, alpha=0.85)
    for i, v in enumerate(vals):
        ax.text(
            v,
            i,
            f" {v:+.1f}",
            va="center",
            ha="left" if v >= 0 else "right",
            fontsize=9,
        )
    ax.axvline(0, color="black", lw=0.6)
    ax.set_title(
        f"Real GDP growth, YoY % — {period} (Eurostat)", fontsize=13, fontweight="bold"
    )
    ax.set_xlabel("% YoY")
    _style(ax)
    return _fig(out / "05_gdp_yoy.png", fig)


def chart_unemployment(dataset: dict, out: Path) -> Path | None:
    series = [s for s in dataset["unemployment_pct"]["series"] if s.get("values")]
    if not series:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, s in enumerate(series):
        xs = [v["period"] for v in s["values"]]
        ys = [v["value"] for v in s["values"]]
        ax.plot(
            xs, ys, marker="", color=_PALETTE[i % len(_PALETTE)], label=_geo_label(s)
        )
    ax.set_title(
        "Unemployment rate, % (Eurostat une_rt_m, SA)", fontsize=13, fontweight="bold"
    )
    ax.set_ylabel("% of labour force")
    ax.legend(fontsize=8)
    _style(ax)
    fig.autofmt_xdate(rotation=45)
    return _fig(out / "06_unemployment.png", fig)


def chart_curated_line(dataset: dict, key: str, out: Path, fname: str) -> Path | None:
    cur = (dataset.get("curated") or {}).get(key)
    if not cur or not cur.get("series"):
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    step = cur.get("step", False)
    for i, s in enumerate(cur["series"]):
        xs = [v["period"] for v in s["values"]]
        ys = [v["value"] for v in s["values"]]
        if step:
            ax.step(
                xs,
                ys,
                where="post",
                marker="o",
                ms=4,
                color=_PALETTE[i % len(_PALETTE)],
                label=s.get("label", ""),
            )
        else:
            ax.plot(
                xs,
                ys,
                marker="o",
                ms=4,
                color=_PALETTE[i % len(_PALETTE)],
                label=s.get("label", ""),
            )
    ax.set_title(cur.get("title", key), fontsize=13, fontweight="bold")
    ax.set_ylabel(cur.get("unit", ""))
    if len(cur["series"]) > 1 or cur["series"][0].get("label"):
        ax.legend(fontsize=8)
    _style(ax)
    fig.autofmt_xdate(rotation=45)
    return _fig(out / fname, fig)


def chart_ai_basket(dataset: dict, out: Path) -> Path | None:
    """European AI / electrification basket, rebased to 100 (AI-axis, Q7)."""
    block = dataset.get("ai_basket", {})
    series = [s for s in block.get("series", []) if s.get("values")]
    if not series:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, s in enumerate(series):
        vals = s["values"]
        base = vals[0]["value"]
        if not base:
            continue
        xs = [v["period"] for v in vals]
        ys = [100 * v["value"] / base for v in vals]
        # NVDA is a US benchmark: dashed to distinguish from European names.
        is_bench = s.get("name") == "nvidia_benchmark"
        ax.plot(
            xs,
            ys,
            marker="" if is_bench else "o",
            ms=3,
            lw=2.0 if is_bench else 1.4,
            ls="--" if is_bench else "-",
            color="#666666" if is_bench else _PALETTE[i % len(_PALETTE)],
            label=s.get("label", s.get("name")),
        )
    ax.axhline(100, color="black", lw=0.6, alpha=0.5)
    ax.set_title(
        "European AI / electrification basket — rebased to 100 (last 12m)",
        fontsize=13,
        fontweight="bold",
    )
    ax.set_ylabel("Price (start = 100)")
    ax.legend(fontsize=7, ncol=2)
    _style(ax)
    fig.autofmt_xdate(rotation=45)
    return _fig(out / "08_ai_basket.png", fig)


def chart_consensus_gdp(dataset: dict, out: Path) -> Path | None:
    """Grouped bars of consensus real-GDP-growth projections by geo (forecast).

    Reads the vintage-tagged consensus block; each bar group is a forecast year.
    Title carries the source vintage so it is never read as realised data.
    """
    proj = (dataset.get("consensus") or {}).get("projections", {})
    recs = [r for r in proj.get("gdp_growth_pct", []) if r.get("values")]
    if not recs:
        return None
    # Restrict to forward years (>= current year) that carry a real forecast.
    want = ["2025", "2026", "2027"]
    labels, per_year = [], {y: [] for y in want}
    for r in recs:
        vmap = {v["period"]: v["value"] for v in r["values"]}
        if not any(y in vmap for y in want):
            continue
        labels.append(r.get("label", r.get("geo")))
        for y in want:
            per_year[y].append(vmap.get(y))
    if not labels:
        return None
    vintages = sorted({r.get("vintage") or r.get("source", "") for r in recs})
    fig, ax = plt.subplots(figsize=(9, 5))
    n = len(labels)
    x = list(range(n))
    width = 0.26
    for j, y in enumerate(want):
        offs = [xi + (j - 1) * width for xi in x]
        ys = [v if v is not None else 0 for v in per_year[y]]
        ax.bar(offs, ys, width=width, color=_PALETTE[j], label=y, alpha=0.85)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.set_title(
        f"Real GDP growth — consensus projection ({', '.join(vintages)})",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("% (annual)")
    ax.legend(fontsize=8, title="forecast yr")
    _style(ax)
    return _fig(out / "09_consensus_gdp.png", fig)


def render_charts(dataset: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    charts: list[Path] = []
    builders = [
        lambda: chart_curated_line(
            dataset, "ecb_rate_path", out_dir, "00_ecb_rate.png"
        ),
        lambda: chart_curated_line(dataset, "hicp_h1_2026", out_dir, "07_hicp_h1.png"),
        lambda: chart_energy(dataset, out_dir),
        lambda: chart_indices(dataset, out_dir),
        lambda: chart_fx(dataset, out_dir),
        lambda: chart_gdp_qoq(dataset, out_dir),
        lambda: chart_gdp_yoy_latest(dataset, out_dir),
        lambda: chart_unemployment(dataset, out_dir),
        lambda: chart_ai_basket(dataset, out_dir),
        lambda: chart_consensus_gdp(dataset, out_dir),
    ]
    for b in builders:
        try:
            p = b()
            if p:
                charts.append(p)
        except Exception:  # noqa: BLE001
            logger.warning("chart failed", exc_info=True)
    return sorted(charts)


# --------------------------------------------------------------------------
# PPTX deck
# --------------------------------------------------------------------------
def build_deck(
    chart_paths: list[Path],
    out_path: Path,
    *,
    title: str,
    subtitle: str,
    source_note: str = (
        "출처: Eurostat, ECB, yfinance, KCIF, 웹 리서치 (data.json 부록)"
    ),
) -> Path:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    dark = RGBColor(0x1B, 0x3A, 0x5C)
    gray = RGBColor(0x66, 0x66, 0x66)

    # Title slide
    s = prs.slides.add_slide(blank)
    box = s.shapes.add_textbox(Inches(0.8), Inches(2.6), Inches(11.7), Inches(2.2))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(34)
    p.font.bold = True
    p.font.color.rgb = dark
    p2 = tf.add_paragraph()
    p2.text = subtitle
    p2.font.size = Pt(18)
    p2.font.color.rgb = gray

    # Chart slides
    for path in chart_paths:
        s = prs.slides.add_slide(blank)
        # image centered, leaving footer
        pic_w = Inches(11.0)
        left = (prs.slide_width - pic_w) / 2
        s.shapes.add_picture(str(path), left, Inches(0.5), width=pic_w)
        fb = s.shapes.add_textbox(Inches(0.5), Inches(7.0), Inches(12.3), Inches(0.4))
        fp = fb.text_frame.paragraphs[0]
        fp.text = source_note
        fp.font.size = Pt(9)
        fp.font.color.rgb = gray
        fp.alignment = PP_ALIGN.CENTER

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    logger.info("Deck saved to %s (%d slides)", out_path, len(prs.slides._sldIdLst))
    return out_path


def save_chart_deck(
    report,
    out_dir: str = "reports",
    *,
    dataset: dict | None = None,
    curated: dict | None = None,
):
    """Build the chart JSON appendix + PNG charts + PPTX deck for a monthly report.

    Returns (deck_path, json_path, chart_paths). If ``dataset`` is not supplied it
    is built live from structured feeds. Files land under reports/euro_macro/ as
    ``{year}-{month:02d}-charts.json``, ``charts_{year}-{month:02d}/`` and
    ``{year}-{month:02d}.pptx``.
    """
    base = Path(out_dir) / "euro_macro"
    tag = f"{report.year}-{report.month:02d}"
    if dataset is None:
        dataset = build_live_dataset(curated=curated)

    json_path = base / f"{tag}-charts.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    charts = render_charts(dataset, base / f"charts_{tag}")
    deck = build_deck(
        charts,
        base / f"{tag}.pptx",
        title=f"유럽 매크로 월간 — {report.year}년 {report.month}월",
        subtitle="차트 대시보드 · 원자료 부록 " + json_path.name,
    )
    return deck, json_path, charts
