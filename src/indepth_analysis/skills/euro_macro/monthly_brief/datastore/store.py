"""시계열 저장소 빌더 — ``ROOT/data/series_store.json``.

    M=indepth_analysis.skills.euro_macro.monthly_brief.datastore.store
    uv run python -m $M build --root reports/euro_macro/monthly_brief/2026-09 \
        --as-of 2026-10-02 [--offline] [--only ea_hicp_headline,ecb_dfr]

- 레지스트리(``registry.SERIES``) 전 계열을 결정론 수집하고 원시 응답을
  ``ROOT/_work/cache/<ns>/``에 캐시한다. 온라인 수집 실패 시 캐시로 폴백(오류 사전에
  ``cache_fallback`` 기록), ``--offline``이면 캐시만 사용.
- 월·분기·연 계열은 첫~마지막 관측 사이 빠진 기간을 ``null``로 채운다(보간 금지).
  일별 계열은 영업일 관측만 둔다.
- ``llm_web``(``web_series_*.json``)은 tier ``llm_web``으로 흡수.
- 파생 계열(``source == "derived"``)은 같은 기간 두 입력이 모두 있을 때만 계산.

산출 스키마(계약 §3)::

    {"as_of","generated_at","series":{id:{title_ko,unit,freq,geo,concept,tier,source,
      dataset,query,url,fetched,points:[[period,value|null,status]],last_period,
      decimals,role,xcheck_of,note}},
     "errors":{id: msg}, "calendar":{"next_releases":{cal_id: date}}}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

from . import ecb, eurostat, market, web_series
from .registry import SERIES, SOURCE_LABEL, SOURCE_TIER, SeriesSpec

UA = "indepth-analysis/3.0 (euro macro monthly brief; deterministic data layer)"


# ---------------------------------------------------------------------------
# 기간 유틸 (chart_pack·table_pack·validate_pack 공용)
# ---------------------------------------------------------------------------
_PAT = {
    "D": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "M": re.compile(r"^\d{4}-\d{2}$"),
    "Q": re.compile(r"^\d{4}-Q[1-4]$"),
    "A": re.compile(r"^\d{4}$"),
}


def period_ok(freq: str, p: str) -> bool:
    pat = _PAT.get(freq)
    return bool(pat and pat.match(p))


def period_index(freq: str, p: str) -> int:
    """월·분기·연 기간을 정수 순번으로 (D는 서수일)."""
    if freq == "M":
        return int(p[:4]) * 12 + int(p[5:7]) - 1
    if freq == "Q":
        return int(p[:4]) * 4 + int(p[6]) - 1
    if freq == "A":
        return int(p[:4])
    if freq == "D":
        return date.fromisoformat(p).toordinal()
    raise ValueError(freq)


def period_from_index(freq: str, i: int) -> str:
    if freq == "M":
        return f"{i // 12:04d}-{i % 12 + 1:02d}"
    if freq == "Q":
        return f"{i // 4:04d}-Q{i % 4 + 1}"
    if freq == "A":
        return f"{i:04d}"
    return date.fromordinal(i).isoformat()


def period_range(freq: str, a: str, b: str) -> list[str]:
    ia, ib = period_index(freq, a), period_index(freq, b)
    return [period_from_index(freq, i) for i in range(ia, ib + 1)]


def period_of_date(freq: str, d: str) -> str:
    """ISO 날짜 → 해당 주기의 기간 라벨."""
    y, m = int(d[:4]), int(d[5:7])
    if freq == "M":
        return f"{y:04d}-{m:02d}"
    if freq == "Q":
        return f"{y:04d}-Q{(m - 1) // 3 + 1}"
    if freq == "A":
        return f"{y:04d}"
    return d[:10]


def fill_gaps(freq: str, pts: list[list]) -> list[list]:
    """M/Q/A: 첫~마지막 사이 누락 기간을 ``[p, None, "final"]``로 채운다."""
    if freq not in ("M", "Q", "A") or not pts:
        return pts
    have = {p[0]: p for p in pts}
    return [
        have.get(p, [p, None, "final"])
        for p in period_range(freq, pts[0][0], pts[-1][0])
    ]


# ---------------------------------------------------------------------------
# 수집 컨텍스트 (HTTP + 캐시)
# ---------------------------------------------------------------------------
class FetchContext:
    def __init__(self, cache_dir: Path, offline: bool = False, timeout: float = 90):
        self.cache_dir = cache_dir
        self.offline = offline
        self.timeout = timeout
        self.fallbacks: list[str] = []
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                timeout=self.timeout, follow_redirects=True, headers={"User-Agent": UA}
            )
        return self._client

    @staticmethod
    def url(base: str, params: list[tuple[str, str]]) -> str:
        return f"{base}?{urlencode(params)}" if params else base

    def _path(self, ns: str, key: str, ext: str) -> Path:
        h = hashlib.sha1(key.encode()).hexdigest()[:10]
        path = urlparse(key).path.rstrip("/")
        seg = "_".join(path.split("/")[-2:]) if path else key
        slug = re.sub(r"[^A-Za-z0-9.]+", "_", seg)[:70]
        return self.cache_dir / ns / f"{slug}_{h}.{ext}"

    def cached_text(self, ns: str, key: str, producer, ext: str = "txt") -> str:
        p = self._path(ns, key, ext)
        if self.offline:
            if not p.exists():
                raise FileNotFoundError(f"오프라인 캐시 없음: {p}")
            return p.read_text(encoding="utf-8")
        try:
            text = producer()
        except Exception as exc:  # noqa: BLE001
            if p.exists():
                self.fallbacks.append(f"{ns}:{key} → 캐시 ({exc})")
                return p.read_text(encoding="utf-8")
            raise
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return text

    def get_text(self, base, params, cache_ns, headers=None) -> str:
        full = self.url(base, params)

        def _get() -> str:
            last: Exception | None = None
            for attempt in range(3):
                try:
                    r = self.client.get(base, params=params, headers=headers or {})
                    r.raise_for_status()
                    return r.text
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    time.sleep(1.5 * (attempt + 1))
            raise last  # type: ignore[misc]

        ext = "json" if cache_ns == "eurostat" else "csv"
        return self.cached_text(cache_ns, full, _get, ext=ext)

    def get_json(self, base, params, cache_ns) -> dict:
        return json.loads(self.get_text(base, params, cache_ns))

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


FETCHERS = {
    "eurostat": eurostat.fetch,
    "ecb": ecb.fetch_ecb,
    "bbk": ecb.fetch_bbk,
    "yf": market.fetch_yf,
    "fred": market.fetch_fred,
    "local_db": market.fetch_local,
}


def _derive(spec: SeriesSpec, series: dict) -> dict:
    q = spec.query
    a, b = series.get(q["a"]), series.get(q["b"])
    if not a or not b:
        raise RuntimeError(f"파생 입력 없음: {q['a']}, {q['b']}")
    bmap = {p[0]: p for p in b["points"]}
    pts = []
    for per, va, sa in a["points"]:
        pb = bmap.get(per)
        if q["op"] == "spread_bp":
            ok = va is not None and pb is not None and pb[1] is not None
            v = round((va - pb[1]) * 100, 1) if ok else None
        else:
            raise ValueError(q["op"])
        st = sa if (pb is None or sa != "final") else pb[2]
        pts.append([per, v, st])
    while pts and pts[-1][1] is None:
        pts.pop()
    return {
        "points": pts,
        "url": a["url"],
        "dataset": a["dataset"],
        "meta": {"inputs": [q["a"], q["b"]], "formula": "(a − b) × 100"},
        "tier": "api" if a["tier"] == b["tier"] == "api" else a["tier"],
        "source_label": a["source"],
    }


def _record(spec: SeriesSpec, res: dict, fetched: str) -> dict:
    pts = fill_gaps(
        spec.freq,
        [[p, round(v, 4) if v is not None else None, st] for p, v, st in res["points"]],
    )
    return {
        "title_ko": spec.title_ko,
        "unit": spec.unit,
        "freq": spec.freq,
        "geo": spec.geo,
        "concept": spec.concept,
        "tier": res.get("tier") or SOURCE_TIER[spec.source],
        "source": res.get("source_label") or SOURCE_LABEL[spec.source],
        "dataset": res["dataset"],
        "query": spec.query,
        "url": res["url"],
        "fetched": fetched,
        "meta": res.get("meta", {}),
        "points": pts,
        "last_period": next((p[0] for p in reversed(pts) if p[1] is not None), None),
        "decimals": spec.decimals,
        "role": spec.role,
        "xcheck_of": spec.xcheck_of,
        "note": spec.note,
    }


def build(
    root: Path,
    as_of: str,
    *,
    offline: bool = False,
    only: set[str] | None = None,
    specs: list[SeriesSpec] | None = None,
) -> dict:
    root = Path(root)
    ctx = FetchContext(root / "_work" / "cache", offline=offline)
    out_path = root / "data" / "series_store.json"
    prior: dict = {}
    if only and out_path.exists():
        prior = json.loads(out_path.read_text(encoding="utf-8"))
    series: dict[str, dict] = dict(prior.get("series", {}))
    errors: dict[str, str] = {
        k: v for k, v in prior.get("errors", {}).items() if only and k not in only
    }
    specs = specs if specs is not None else SERIES
    derived = [s for s in specs if s.source == "derived"]
    for spec in specs:
        if spec.source == "derived" or (only and spec.id not in only):
            continue
        fetched = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            res = FETCHERS[spec.source](spec, ctx)
            if not any(p[1] is not None for p in res["points"]):
                raise RuntimeError("관측값 없음")
            series[spec.id] = _record(spec, res, fetched)
        except Exception as exc:  # noqa: BLE001
            errors[spec.id] = f"{type(exc).__name__}: {str(exc)[:240]}"
            series.pop(spec.id, None)
    for spec in derived:
        if (
            only
            and spec.id not in only
            and not ({spec.query["a"], spec.query["b"]} & only)
        ):
            continue
        try:
            res = _derive(spec, series)
            series[spec.id] = _record(spec, res, series[spec.query["a"]]["fetched"])
        except Exception as exc:  # noqa: BLE001
            errors[spec.id] = f"{type(exc).__name__}: {exc}"
    web, web_err = web_series.load(root)
    for sid, rec in web.items():
        if sid in series and series[sid].get("tier") != "llm_web":
            errors[f"web:{sid}"] = "레지스트리 id와 충돌 — 흡수 생략"
            continue
        series[sid] = rec
    errors.update(web_err)
    ref = min(as_of, date.today().isoformat())
    cal = (
        market.next_releases(ref)
        if not offline
        else prior.get("calendar", {}).get("next_releases", {})
    )
    if offline and not cal and out_path.exists():
        cal = (
            json.loads(out_path.read_text(encoding="utf-8"))
            .get("calendar", {})
            .get("next_releases", {})
        )
    doc = {
        "as_of": as_of,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "series": dict(sorted(series.items())),
        "errors": dict(sorted(errors.items())),
        "cache_fallbacks": ctx.fallbacks,
        "calendar": {"next_releases": cal, "reference_date": ref},
    }
    ctx.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return doc


def load_store(root: Path) -> dict:
    return json.loads((Path(root) / "data" / "series_store.json").read_text("utf-8"))


def summary(doc: dict) -> str:
    from collections import Counter

    tiers = Counter(s["tier"] for s in doc["series"].values())
    lines = [f"series {len(doc['series'])} {dict(tiers)} errors {len(doc['errors'])}"]
    for k, v in doc["errors"].items():
        lines.append(f"  ERR {k}: {v}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="datastore.store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--root", required=True)
    b.add_argument("--as-of", default="")
    b.add_argument("--offline", action="store_true")
    b.add_argument("--only", default="", help="쉼표 구분 id (부분 갱신)")
    a = ap.parse_args(argv)
    root = Path(a.root)
    as_of = a.as_of
    if not as_of:
        ed = json.loads((root / "edition.json").read_text(encoding="utf-8"))
        as_of = ed["as_of"]
    only = {x for x in a.only.split(",") if x} or None
    doc = build(root, as_of, offline=a.offline, only=only)
    print(summary(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
