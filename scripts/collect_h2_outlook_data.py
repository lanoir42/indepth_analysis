"""Collect the verified quantitative backbone for the H2-2026 Euro-macro outlook.

Same anti-hallucination principle as ``collect_h1h2_data.py``: every keyless
structured client runs best-effort and writes a single data.json with source
metadata on every series. This forward-looking variant adds a consensus/forecast
block (IMF WEO + OECD EO projections, vintage-tagged) and an AI/electrification
equity basket, and widens the KCIF semantic window toward the H2 outlook themes.

Usage:
    uv run python scripts/collect_h2_outlook_data.py
Output:
    reports/euro_macro_h2_outlook_2026/data.json
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from indepth_analysis.config import ReferenceConfig
from indepth_analysis.data.consensus_client import ConsensusClient
from indepth_analysis.data.ecb_client import ECBClient
from indepth_analysis.data.energy_client import EnergyClient
from indepth_analysis.data.eurostat_client import (
    COICOP_ALL,
    COICOP_CORE,
    COICOP_ENERGY,
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("collect_h2")

OUT_DIR = Path("reports/euro_macro_h2_outlook_2026")
GEOS = [GEO_EA20, GEO_EU27, GEO_DE, GEO_FR, GEO_IT, GEO_ES]

# Wider window: H1-2026 realised data + late-2024 base for trend context.
EUROSTAT_START = "2024-06"
EUROSTAT_START_Q = "2024-Q1"
KCIF_FROM = "2026-01-01"
KCIF_TO = "2026-07-31"

KCIF_QUERIES = [
    "유럽 하반기 경제 전망 성장",
    "ECB 금리 인하 통화정책 전망",
    "유로존 인플레이션 물가 전망",
    "유럽 에너지 천연가스 겨울 재고",
    "유럽 전력 데이터센터 전력수요",
    "인공지능 AI 투자 반도체 유럽",
    "유럽 재정 국채 국방 지출",
    "유럽 성장 경기 리스크 시나리오",
    "러시아 우크라이나 제재 지정학 전쟁",
    "미국 관세 무역 유럽 영향",
]


def _clean(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, float):
        return round(v, 4)
    return v


def eurostat_series(df: pd.DataFrame, group_cols: list[str]) -> list[dict]:
    """Group a tidy Eurostat frame into per-entity {meta, values[]} records."""
    if df is None or df.empty or "value" not in df.columns:
        return []
    time_col = "time" if "time" in df.columns else None
    if time_col is None:
        return []
    present = [c for c in group_cols if c in df.columns]
    out: list[dict] = []
    for keys, g in df.groupby(present):
        keys = keys if isinstance(keys, tuple) else (keys,)
        meta = dict(zip(present, keys))
        for c in present:
            lbl = f"{c}_label"
            if lbl in g.columns:
                meta[lbl] = str(g[lbl].iloc[0])
        g2 = g.sort_values(time_col)
        values = [
            {"period": str(t), "value": _clean(v)}
            for t, v in zip(g2[time_col], g2["value"])
            if _clean(v) is not None
        ]
        if values:
            out.append({**meta, "values": values})
    return out


def collect_eurostat() -> dict:
    es = EurostatClient()
    block: dict = {}
    try:
        hicp = es.get_hicp(
            geos=GEOS,
            coicops=[COICOP_ALL, COICOP_CORE, COICOP_ENERGY],
            start_period=EUROSTAT_START,
            rate=True,
        )
        block["hicp_yoy_pct"] = {
            "source": "eurostat",
            "series_id": "prc_hicp_manr",
            "unit": "% YoY",
            "series": eurostat_series(hicp, ["geo", "coicop"]),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("eurostat HICP failed: %s", e)
        block["hicp_yoy_pct"] = {"source": "eurostat", "error": str(e), "series": []}

    try:
        gdp_q = es.get_gdp(geos=GEOS, start_period=EUROSTAT_START_Q, unit=GDP_UNIT_QOQ)
        block["gdp_qoq_pct"] = {
            "source": "eurostat",
            "series_id": "namq_10_gdp (CLV_PCH_PRE)",
            "unit": "% QoQ",
            "series": eurostat_series(gdp_q, ["geo"]),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("eurostat GDP QoQ failed: %s", e)
        block["gdp_qoq_pct"] = {"source": "eurostat", "error": str(e), "series": []}

    try:
        gdp_y = es.get_gdp(geos=GEOS, start_period=EUROSTAT_START_Q, unit=GDP_UNIT_YOY)
        block["gdp_yoy_pct"] = {
            "source": "eurostat",
            "series_id": "namq_10_gdp (CLV_PCH_SM)",
            "unit": "% YoY",
            "series": eurostat_series(gdp_y, ["geo"]),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("eurostat GDP YoY failed: %s", e)
        block["gdp_yoy_pct"] = {"source": "eurostat", "error": str(e), "series": []}

    try:
        unemp = es.get_unemployment(geos=GEOS, start_period=EUROSTAT_START)
        block["unemployment_pct"] = {
            "source": "eurostat",
            "series_id": "une_rt_m",
            "unit": "% of labour force",
            "series": eurostat_series(unemp, ["geo"]),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("eurostat unemployment failed: %s", e)
        block["unemployment_pct"] = {
            "source": "eurostat",
            "error": str(e),
            "series": [],
        }

    try:
        ip = es.get_industrial_production(geos=GEOS, start_period=EUROSTAT_START)
        block["industrial_production_idx"] = {
            "source": "eurostat",
            "series_id": "sts_inpr_m (I21, B-D)",
            "unit": "index 2021=100",
            "series": eurostat_series(ip, ["geo"]),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("eurostat IP failed: %s", e)
        block["industrial_production_idx"] = {
            "source": "eurostat",
            "error": str(e),
            "series": [],
        }

    es.close()
    return block


def collect_ecb() -> dict:
    """ECB policy rates + EUR FX via DBnomics (keyless). Defensive serialize."""
    block: dict = {}
    try:
        ecb = ECBClient()
        raw = ecb.fetch_all()
        for key, df in raw.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                cols = [
                    c
                    for c in df.columns
                    if c.lower() in ("date", "time", "period", "value")
                    or df[c].dtype == object
                ]
                trimmed = df[cols] if cols else df
                recs = [
                    {k: _clean(v) for k, v in r.items()}
                    for r in trimmed.tail(400).to_dict("records")
                ]
                block[key] = {"source": "ecb_dbnomics", "records": recs}
            else:
                block[key] = {"source": "ecb_dbnomics", "records": []}
    except Exception as e:  # noqa: BLE001
        logger.warning("ECB fetch failed: %s", e)
        block["error"] = str(e)
    return block


def collect_energy() -> dict:
    try:
        return EnergyClient().fetch_all(period="1y")
    except Exception as e:  # noqa: BLE001
        logger.warning("energy fetch failed: %s", e)
        return {"error": str(e), "energy": [], "indices": [], "fx": [], "ai_basket": []}


def collect_consensus() -> dict:
    """Forward projections (IMF WEO + OECD EO via DBnomics), vintage-tagged.

    These structured feeds lag (DBnomics carries IMF WEO through 2025-04 only),
    so they are a cross-check, NOT the primary anchor: the report's current
    forward numbers (ECB June-2026 staff projections, EC Spring-2026 forecast)
    come from the web team with citations. The vintage tag prevents any stale
    forecast from being presented as current.
    """
    try:
        c = ConsensusClient()
        res = c.fetch_all()
        c.close()
        return {
            "source": "dbnomics (IMF WEO / OECD EO)",
            "note": (
                "Vintage-tagged structured cross-check only. Primary H2 forward "
                "anchors (ECB/EC) are web-sourced with citations."
            ),
            "projections": res,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("consensus fetch failed: %s", e)
        return {"source": "dbnomics", "error": str(e), "projections": {}}


def collect_kcif() -> dict:
    """H1-2026 semantic search over the KCIF corpus (qualitative context)."""
    try:
        import numpy as np

        from indepth_analysis.db import ReferenceDB
        from indepth_analysis.processing.embedder import get_embedder
        from indepth_analysis.search.indexer import SearchIndex

        cfg = ReferenceConfig()
        db = ReferenceDB(Path(cfg.db_path))
        index = SearchIndex()
        index.build(db)
        if index.size == 0:
            db.close()
            return {"source": "kcif", "note": "empty index", "findings": []}

        rows = db.conn.execute(
            "SELECT id FROM reports WHERE published_date >= ? AND published_date <= ?",
            (KCIF_FROM, KCIF_TO),
        ).fetchall()
        rfilter = {r["id"] for r in rows} if rows else None

        embedder = get_embedder(cfg)
        seen: set[int] = set()
        findings: list[dict] = []
        for q in KCIF_QUERIES:
            vec = np.frombuffer(embedder.embed(q), dtype=np.float32)
            for chunk, score in index.search(vec, top_k=8, report_id_filter=rfilter):
                if chunk.report_id in seen or score < 0.3:
                    continue
                report = db.get_report_by_id(chunk.report_id)
                if not report:
                    continue
                findings.append(
                    {
                        "query": q,
                        "title": report.title,
                        "published_date": report.published_date,
                        "url": report.url,
                        "score": round(float(score), 4),
                        "snippet": chunk.content[:1200],
                    }
                )
                seen.add(chunk.report_id)
        db.close()
        return {
            "source": "kcif",
            "window": [KCIF_FROM, KCIF_TO],
            "filtered_reports": len(rfilter) if rfilter else 0,
            "findings": findings,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("KCIF search failed: %s", e)
        return {"source": "kcif", "error": str(e), "findings": []}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Collecting Eurostat ...")
    eurostat = collect_eurostat()
    logger.info("Collecting ECB ...")
    ecb = collect_ecb()
    logger.info("Collecting energy / indices / fx / ai-basket ...")
    energy = collect_energy()
    logger.info("Collecting consensus / forecast projections ...")
    consensus = collect_consensus()
    logger.info("Collecting KCIF context ...")
    kcif = collect_kcif()

    data = {
        "meta": {
            "report": "euro_macro_h2_outlook_2026",
            "as_of": date.today().isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "note": (
                "Verified structured backbone for the H2-2026 outlook. Every "
                "series carries its source. Consensus projections are vintage-"
                "tagged cross-checks; current ECB/EC forecasts and EUA carbon / "
                "German baseload power / gas storage are web-sourced with "
                "citations rather than faked here."
            ),
        },
        "eurostat": eurostat,
        "ecb": ecb,
        "market": energy,
        "consensus": consensus,
        "kcif_context": kcif,
    }

    out = OUT_DIR / "data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    n_series = sum(
        len(v.get("series", [])) for v in eurostat.values() if isinstance(v, dict)
    )
    logger.info("Wrote %s", out)
    logger.info("Eurostat entity-series: %d", n_series)
    for grp in ("energy", "indices", "fx", "ai_basket"):
        items = energy.get(grp, []) if isinstance(energy, dict) else []
        got = [i["name"] for i in items if i.get("latest") is not None]
        logger.info("market/%s: %d/%d with data %s", grp, len(got), len(items), got)
    proj = consensus.get("projections", {})
    for metric, recs in proj.items():
        resolved = [r["geo"] for r in recs if r.get("values")]
        logger.info("consensus/%s: %d resolved %s", metric, len(resolved), resolved)
    logger.info("KCIF findings: %d", len(kcif.get("findings", [])))


if __name__ == "__main__":
    main()
