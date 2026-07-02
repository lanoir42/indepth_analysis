"""Build the Euro-macro monthly chart appendix (JSON) + chart PNGs + PPTX deck.

Uses the verified H1/H2 data.json backbone plus curated series (ECB policy-rate
path, H1-2026 energy-HICP reacceleration) sourced from the web-research findings,
since the structured feeds lag. Outputs live under reports/euro_macro/.

Usage: uv run python scripts/build_euro_macro_deck.py
"""

from __future__ import annotations

import json
from pathlib import Path

from indepth_analysis.skills.euro_macro.macro_charts import (
    build_chart_dataset,
    build_deck,
    render_charts,
)

BACKBONE = Path("reports/euro_macro_h1h2_2026/data.json")
OUT_DIR = Path("reports/euro_macro")
CHART_DIR = OUT_DIR / "charts_2026-07"
CHART_JSON = OUT_DIR / "2026-07-charts.json"
DECK = OUT_DIR / "2026-07.pptx"

# Curated series (sourced from web-research findings; structured feeds lag).
CURATED = {
    "ecb_rate_path": {
        "title": "ECB Deposit Facility Rate — cut cycle to first hike",
        "unit": "%",
        "step": True,
        "source": "ECB press releases (findings/ecb.md): 3.00% 2025-02; "
        "8 cuts to 2.00% by 2025-06-11; holds 2026-02/03/04; +25bp to 2.25% 2026-06-11",
        "series": [
            {
                "label": "ECB DFR",
                "values": [
                    {"period": "2025-02", "value": 3.00},
                    {"period": "2025-06", "value": 2.00},
                    {"period": "2025-12", "value": 2.00},
                    {"period": "2026-04", "value": 2.00},
                    {"period": "2026-06", "value": 2.25},
                    {"period": "2026-07", "value": 2.25},
                ],
            }
        ],
    },
    "hicp_h1_2026": {
        "title": "EA20 energy HICP, YoY% — war-driven reacceleration (2026 H1)",
        "unit": "% YoY (energy component)",
        "step": False,
        "source": "Eurostat/ECB via findings/energy.md (Dec-2025 backbone snapshot "
        "was -1.9% pre-war; path below is the H1-2026 realised reacceleration)",
        "series": [
            {
                "label": "EA20 energy HICP",
                "values": [
                    {"period": "2026-01", "value": -4.1},
                    {"period": "2026-02", "value": -3.1},
                    {"period": "2026-03", "value": 5.1},
                    {"period": "2026-04", "value": 10.8},
                    {"period": "2026-05", "value": 10.9},
                ],
            }
        ],
    },
}


def main() -> None:
    dataset = build_chart_dataset(BACKBONE, curated=CURATED, refresh_market=True)
    CHART_JSON.parent.mkdir(parents=True, exist_ok=True)
    CHART_JSON.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"chart JSON -> {CHART_JSON}")

    charts = render_charts(dataset, CHART_DIR)
    print(f"rendered {len(charts)} charts:")
    for c in charts:
        print("  ", c)

    deck = build_deck(
        charts,
        DECK,
        title="유럽 매크로 월간 업데이트 — 2026년 7월",
        subtitle="2026 상반기 결산 & 하반기 전망 기반 · 차트 부록",
    )
    print(f"deck -> {deck}")


if __name__ == "__main__":
    main()
