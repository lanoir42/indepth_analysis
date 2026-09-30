"""웹 리서치 시계열(llm_web) 흡수 — ``ROOT/data/web_series_<KEY>.json``.

입력 형식(v2 ``SERIES_HEADER``와 동일)::

    {"as_of": "...", "series": {"<id>": {"title","unit","frequency","x_labels",
      "data","source","url","published","note"}}, "unresolved": [...]}

- 모든 포인트는 tier ``llm_web``. ``x_labels``와 ``data`` 길이가 다르면 해당 계열 오류.
- 상태: 기본 ``final``; ``note``에 flash/속보가 있으면 마지막 포인트만 ``flash``;
  ``status`` 배열이 주어지면 그대로 사용.
- 알려진 id는 ``registry.WEB_SERIES_MAP``으로 concept·한국어 제목을 붙이고, 모르는 id는
  ``web_<id>`` concept로 보존한다(차트에는 쓰이지 않음).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .registry import WEB_SERIES_MAP

_Q = re.compile(r"^(\d{4})[- ]?Q([1-4])$")
_M = re.compile(r"^(\d{4})-(\d{1,2})$")


def _norm_label(lab: str, freq: str) -> str:
    s = str(lab).strip()
    if m := _Q.match(s):
        return f"{m.group(1)}-Q{m.group(2)}"
    if m := _M.match(s):
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return s


def load(root: Path) -> tuple[dict[str, dict], dict[str, str]]:
    series: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for f in sorted((root / "data").glob("web_series_*.json")):
        key = f.stem.removeprefix("web_series_")
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors[f"web:{key}"] = f"JSON 파싱 실패: {exc}"
            continue
        for sid, s in (doc.get("series") or {}).items():
            labels, data = s.get("x_labels") or [], s.get("data") or []
            if len(labels) != len(data):
                errors[sid] = f"{f.name}: x_labels {len(labels)} ≠ data {len(data)}"
                continue
            raw_freq = (s.get("frequency") or "M").strip()
            # 'meeting' 등 비정규 빈도는 이벤트(E) ('meeting'[:1]='M' 오분류 방지)
            freq = raw_freq.upper() if raw_freq.upper() in ("D", "M", "Q", "A") else "E"
            concept, title, unit = WEB_SERIES_MAP.get(
                sid, (f"web_{sid}", s.get("title") or sid, s.get("unit") or "")
            )
            status = s.get("status")
            note = s.get("note") or ""
            pts = []
            for i, (lab, v) in enumerate(zip(labels, data, strict=True)):
                if isinstance(status, list) and i < len(status):
                    st = status[i]
                elif i == len(labels) - 1 and re.search(r"flash|속보", note, re.I):
                    st = "flash"
                else:
                    st = "final"
                val = float(v) if isinstance(v, (int, float)) else None
                pts.append([_norm_label(lab, freq), val, st])
            pts.sort(key=lambda p: p[0])
            series[sid] = {
                "title_ko": title,
                "unit": s.get("unit") or unit,
                "freq": "E" if freq not in "DMQA" else freq,
                "geo": sid[:2].upper()
                if sid[:2] in ("ea", "de", "fr", "it", "es")
                else "EA",
                "concept": concept,
                "tier": "llm_web",
                "source": s.get("source") or "웹 리서치",
                "dataset": f"web_series_{key}",
                "query": {"file": f.name, "id": sid},
                "url": s.get("url") or "",
                "fetched": doc.get("as_of") or "",
                "published": s.get("published") or "",
                "points": pts,
                "last_period": next(
                    (p[0] for p in reversed(pts) if p[1] is not None), None
                ),
                "decimals": 1,
                "role": "primary",
                "note": note,
            }
    return series, errors
