"""Eurostat JSON-stat 2.0 수집기.

- 기본 URL ``https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/<ds>``
- 값 위치 = 차원 인덱스의 행우선(row-major) 평탄화 — 마지막 차원(time)이 가장 빠름.
- ``status`` 플래그: ``p`` → prelim, ``e`` → estimate, 그 외(없음·``b``·``d``) → final.
- 지역 후보(``geo_candidates``): 유로존은 데이터셋마다 EA·EA21·EA20이 다르므로 한 번에
  요청해 최신 비결측 관측이 가장 늦은 코드를 고른다(동률이면 목록 순서).
- HICP 속보(``hicp_flash``): ``prc_hicp_fpd``(release=FLS)에서 ``prc_hicp_minr``
  마지막 기간 이후 달을 ``flash``로 덧붙인다.
"""

from __future__ import annotations

import itertools
from typing import Any

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
FLAG_STATUS = {"p": "prelim", "e": "estimate", "f": "estimate"}


def parse_jsonstat(j: dict) -> list[dict[str, Any]]:
    """JSON-stat 응답 → ``[{dim: code, ..., "time": t, "value": v, "flag": f}]``.

    값이 없는 셀도 ``value=None``으로 포함한다(격자 보존).
    """
    ids: list[str] = j.get("id", [])
    sizes: list[int] = j.get("size", [])
    if not ids or not sizes or 0 in sizes:
        return []
    cats: list[list[str]] = []
    for d in ids:
        idx = j["dimension"][d]["category"]["index"]
        if isinstance(idx, list):
            cats.append(list(idx))
        else:
            cats.append([k for k, _ in sorted(idx.items(), key=lambda kv: kv[1])])
    values = j.get("value", {}) or {}
    status = j.get("status", {}) or {}
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values) if v is not None}
    if isinstance(status, list):
        status = {str(i): v for i, v in enumerate(status) if v}
    out: list[dict[str, Any]] = []
    for combo in itertools.product(*[range(s) for s in sizes]):
        flat = 0
        for k, s in zip(combo, sizes, strict=True):
            flat = flat * s + k
        key = str(flat)
        rec = {ids[i]: cats[i][k] for i, k in enumerate(combo)}
        v = values.get(key)
        rec["value"] = float(v) if v is not None else None
        rec["flag"] = status.get(key, "")
        out.append(rec)
    return out


def _params(filters: dict, geos: list[str], since: str) -> list[tuple[str, str]]:
    p: list[tuple[str, str]] = []
    for k, v in filters.items():
        for x in v if isinstance(v, list) else [v]:
            p.append((k, str(x)))
    for g in geos:
        p.append(("geo", g))
    if since:
        p.append(("sinceTimePeriod", since))
    return p


def _pick_geo(rows: list[dict], geos: list[str]) -> tuple[str, list[dict]]:
    best, best_last = geos[0], ""
    for g in geos:
        obs = [r for r in rows if r.get("geo") == g and r["value"] is not None]
        last = max((r["time"] for r in obs), default="")
        if last > best_last:
            best, best_last = g, last
    return best, [r for r in rows if r.get("geo") == best]


def _to_points(rows: list[dict]) -> list[list]:
    pts = []
    for r in sorted(rows, key=lambda r: r["time"]):
        st = FLAG_STATUS.get((r.get("flag") or "").lower()[:1], "final")
        pts.append([r["time"], r["value"], st])
    # 뒤쪽 결측(아직 미발표 기간)은 잘라낸다 — 앞·중간 결측은 null 유지
    while pts and pts[-1][1] is None:
        pts.pop()
    while pts and pts[0][1] is None:
        pts.pop(0)
    return pts


def fetch(spec, ctx) -> dict:
    q = spec.query
    ds = q["dataset"]
    geos = q.get("geo_candidates") or [spec.geo]
    params = _params(q["filters"], geos, spec.start)
    j = ctx.get_json(BASE + ds, params, cache_ns="eurostat")
    rows = parse_jsonstat(j)
    geo, rows = _pick_geo(rows, geos)
    pts = _to_points(rows)
    meta = {"dataset": ds, "geo_code": geo, "updated": j.get("updated", "")}
    url = ctx.url(BASE + ds, params)
    if spec.status_rule == "hicp_flash" and pts:
        n = apply_hicp_flash(pts, _fpd(spec, ctx, geo, pts[-1][0]))
        if n:
            meta["flash_dataset"] = "prc_hicp_fpd"
    return {"points": pts, "url": url, "dataset": ds, "meta": meta}


def _fpd(spec, ctx, geo: str, last_period: str) -> list[dict]:
    """``prc_hicp_fpd``(속보 FLS·확정 FIN) — 마지막 확정월 2개월 전부터."""
    y, m = int(last_period[:4]), int(last_period[5:7])
    m -= 2
    if m < 1:
        y, m = y - 1, m + 12
    f = dict(spec.query["filters"])
    f["release"] = ["FLS", "FIN"]
    params = _params(f, [geo], f"{y:04d}-{m:02d}")
    try:
        j = ctx.get_json(BASE + "prc_hicp_fpd", params, cache_ns="eurostat")
    except Exception:  # noqa: BLE001 — 속보 보강 실패는 비치명
        return []
    return parse_jsonstat(j)


def apply_hicp_flash(pts: list[list], fpd_rows: list[dict]) -> int:
    """속보 규칙 적용 — 확정(FIN) 없이 속보(FLS)만 있는 달은 ``flash``.

    ``prc_hicp_minr`` 마지막 달 이후의 속보는 덧붙이고, 이미 들어 있는 달이라도
    확정치가 없으면 상태를 ``flash``로 바꾼다. 반환: 적용 건수.
    """
    fls = {r["time"]: r["value"] for r in fpd_rows if r.get("release") == "FLS"}
    fin = {r["time"]: r["value"] for r in fpd_rows if r.get("release") == "FIN"}
    n = 0
    have = {p[0]: p for p in pts}
    for t in sorted(fls):
        if fls[t] is None or fin.get(t) is not None:
            continue
        if t in have:
            have[t][2] = "flash"
        elif not pts or t > pts[-1][0]:
            pts.append([t, fls[t], "flash"])
        n += 1
    return n
