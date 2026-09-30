"""ECB Data Portal · Bundesbank SDMX(CSV) 수집기.

- ECB: ``https://data-api.ecb.europa.eu/service/data/<FLOW>/<KEY>?format=csvdata``
- Bundesbank: ``https://api.statistiken.bundesbank.de/rest/data/<FLOW>/<KEY>``
  (Accept ``application/vnd.sdmx.data+csv;version=1.0.0``, 구분자 ``;``)
- ``OBS_STATUS``: ``P`` → prelim, ``E`` → estimate, 그 외 → final.
  ``status_rule == "spot"``이면 전부 ``spot``.
"""

from __future__ import annotations

import csv
import io

ECB_BASE = "https://data-api.ecb.europa.eu/service/data/"
BBK_BASE = "https://api.statistiken.bundesbank.de/rest/data/"
OBS_STATUS = {"P": "prelim", "E": "estimate", "F": "flash"}
BBK_ACCEPT = "application/vnd.sdmx.data+csv;version=1.0.0"


def parse_sdmx_csv(text: str) -> list[tuple[str, float | None, str]]:
    """SDMX-CSV → ``[(TIME_PERIOD, value|None, OBS_STATUS)]`` (구분자 자동 감지)."""
    text = text.lstrip("﻿")
    if not text.strip():
        return []
    head = text.splitlines()[0]
    delim = ";" if head.count(";") > head.count(",") else ","
    out = []
    for row in csv.DictReader(io.StringIO(text), delimiter=delim):
        t = (row.get("TIME_PERIOD") or "").strip()
        if not t:
            continue
        raw = (row.get("OBS_VALUE") or "").strip().replace(",", ".")
        try:
            v: float | None = float(raw) if raw not in ("", ".", "NaN") else None
        except ValueError:
            v = None
        out.append((t, v, (row.get("OBS_STATUS") or "").strip()))
    return out


def _points(rows, rule: str, start: str) -> list[list]:
    pts = []
    for t, v, st in sorted(rows):
        if start and t < start:
            continue
        status = "spot" if rule == "spot" else OBS_STATUS.get(st, "final")
        pts.append([t, v, status])
    while pts and pts[-1][1] is None:
        pts.pop()
    return pts


def fetch_ecb(spec, ctx) -> dict:
    key = spec.query["key"]
    start = spec.start
    params = [("format", "csvdata"), ("startPeriod", start)]
    url = ECB_BASE + key
    text = ctx.get_text(url, params, cache_ns="ecb")
    rows = parse_sdmx_csv(text)
    if spec.freq == "D":  # 일별 계열의 휴일 결측(빈 값)은 관측 아님 → 제거
        rows = [r for r in rows if r[1] is not None]
    return {
        "points": _points(rows, spec.status_rule, start),
        "url": ctx.url(url, params),
        "dataset": key.split("/")[0],
        "meta": {"key": key},
    }


def fetch_bbk(spec, ctx) -> dict:
    flow, key = spec.query["flow"], spec.query["key"]
    params = [("startPeriod", spec.start)]
    url = f"{BBK_BASE}{flow}/{key}"
    text = ctx.get_text(url, params, cache_ns="bbk", headers={"Accept": BBK_ACCEPT})
    rows = [r for r in parse_sdmx_csv(text) if r[1] is not None]
    return {
        "points": _points(rows, spec.status_rule, spec.start),
        "url": ctx.url(url, params),
        "dataset": flow,
        "meta": {"key": f"{flow}.{key}"},
    }
