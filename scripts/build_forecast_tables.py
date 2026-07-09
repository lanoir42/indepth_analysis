"""Render institution forecast comparison tables from a verified JSON.

Part of the routinized forecast-table pipeline: takes the QA-passed forecast
JSON (assembled from sourced web research) and renders the Notion-safe
comparison-table markdown. Never invents values — missing cells render as
"미확인".

Usage:
    uv run python scripts/build_forecast_tables.py <forecast.json> <out.md>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from indepth_analysis.skills.euro_macro.forecast_tables import (
    build_from_json,
    validate,
)


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: build_forecast_tables.py <forecast.json> <out.md>")
        raise SystemExit(2)
    src, out = sys.argv[1], sys.argv[2]
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    problems = validate(data)
    if problems:
        print("SCHEMA 경고:")
        for p in problems:
            print("  -", p)
    path = build_from_json(src, out)
    print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
