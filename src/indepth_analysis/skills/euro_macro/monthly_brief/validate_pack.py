"""차트·표 팩 검증기 — ``ROOT/data/validation.json`` (FAIL 시 종료코드 1).

    M=indepth_analysis.skills.euro_macro.monthly_brief.validate_pack
    uv run python -m $M --root reports/euro_macro/monthly_brief/2026-09

규칙 (id · 수준)
- S1 FAIL  저장소 기간 라벨이 주기 형식과 불일치
- S2 WARN  저장소 수집 오류 존재
- S3 FAIL  primary 계열 간 concept 중복
- C1 FAIL  kind·section 값이 허용 목록 밖
- C2 FAIL  한 차트에 주기 혼합(계열 freq ≠ x.type)
- C3 FAIL  x 라벨 형식 불일치·중복·역순, 월/분기/연 격자 누락(라벨 삭제)
- C4 FAIL  계열 values/status 길이 ≠ x 라벨 수
- C5 FAIL  단위·축·등급·출처·색 역할·gap 메타 누락/오류
- C6 FAIL  CSV 누락 또는 CSV ↔ JSON 값 불일치
- C7 FAIL  제목·부제 수치가 CSV 값(선언 자릿수 문자열)과 불일치
- C8 WARN  최신성 지연(HICP ≤ 2개월, GDP ≤ 2분기, 일별 ≤ 5일, 기타 월 ≤ 3개월 …)
- C9 FAIL  한 차트 안 같은 concept 중복
- C10 WARN llm_web 계열이 headline 차트에 사용됨
- C11 WARN 교차검증 허용오차 초과(llm_web·xcheck ↔ 기준 계열)
- C12 WARN 계열 전체가 결측
- P1 WARN  차트 < 20 또는 표 < 8, 결정론 등급 비율 < 80%
- T1 FAIL  표 변화 열 재계산 불일치
- T2 FAIL  표 열 메타 누락
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from .chart_pack import KINDS, SECTIONS, fmt
from .datastore.registry import TIERS, XCHECK_TOL
from .datastore.store import period_index, period_ok

XFREQ = {"month": "M", "quarter": "Q", "year": "A", "day": "D", "category": "C"}
COLOR_ROLES = ("primary", "secondary", "accent", "neutral", "negative")
NUM = re.compile(r"([$€]?)([+\-−]?\d[\d,]*(?:\.\d+)?)(%p|%|bp|pt)?")
SKIP_AFTER = ("년", "월", "일", "분기", "개", "Q", ":")


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, rule: str, level: str, target: str, msg: str) -> None:
        self.items.append({"rule": rule, "level": level, "target": target, "msg": msg})

    @property
    def status(self) -> str:
        levels = {i["level"] for i in self.items}
        return "FAIL" if "FAIL" in levels else "WARN" if "WARN" in levels else "PASS"


# ---------------------------------------------------------------------------
def title_numbers(text: str) -> list[str]:
    """제목·부제에서 검증 대상 수치 토큰(소수점·단위·통화 기호 동반)을 추출."""
    out = []
    for m in NUM.finditer(text):
        cur, num, unit = m.group(1), m.group(2), m.group(3)
        start, end = m.start(2), m.end()
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        if before.isalpha() and before.isascii():  # G47·EXV1 등 식별자
            continue
        if not unit and after in SKIP_AFTER:
            continue
        if not (cur or unit or "." in num):
            continue
        out.append(num.replace("−", "-").replace("+", "").replace(",", ""))
    return out


def _lag(freq: str, last: str, as_of: str) -> int:
    if freq == "D":
        return (date.fromisoformat(as_of) - date.fromisoformat(last)).days
    ref = {
        "M": as_of[:7],
        "Q": f"{as_of[:4]}-Q{(int(as_of[5:7]) - 1) // 3 + 1}",
        "A": as_of[:4],
    }[freq]
    return period_index(freq, ref) - period_index(freq, last)


def freshness_limit(concept: str, freq: str) -> int | None:
    if freq == "D":
        # FRED 현물 Brent(DCOILBRENTEU)는 원천(EIA) 게시가 통상 1주 지연
        return 12 if "dated" in concept else 5
    if freq == "M":
        return (
            2
            if concept.startswith(("hicp", "pmi", "esi", "consumer", "industry_c"))
            else 3
        )
    if freq == "Q":
        return 2 if concept.startswith("gdp") else 3
    if freq == "A":
        return 2
    return None


def check_store(store: dict, rep: Report) -> None:
    concepts: dict[str, str] = {}
    for sid, s in store["series"].items():
        if s["freq"] in "DMQA":
            bad = [p[0] for p in s["points"] if not period_ok(s["freq"], p[0])]
            if bad:
                rep.add("S1", "FAIL", sid, f"기간 라벨 형식 오류 {bad[:3]}")
        if s.get("role", "primary") == "primary":
            c = s["concept"]
            if c in concepts:
                rep.add("S3", "FAIL", sid, f"concept '{c}' 중복: {concepts[c]}")
            concepts[c] = sid
    for k, v in store.get("errors", {}).items():
        rep.add("S2", "WARN", k, v)
    # 교차검증: xcheck·llm_web ↔ 기준 concept
    by_concept = {
        s["concept"]: (sid, s)
        for sid, s in store["series"].items()
        if s.get("role", "primary") == "primary"
    }
    for sid, s in store["series"].items():
        if s.get("role") != "xcheck":
            continue
        target = by_concept.get(s.get("xcheck_of", ""))
        if not target:
            continue
        tid, t = target
        tol = XCHECK_TOL.get(s["xcheck_of"], 0.05)
        tmap = {p[0]: p[1] for p in t["points"] if p[1] is not None}
        bad = []
        for p, v, _ in s["points"]:
            if v is None or p not in tmap:
                continue
            if abs(v - tmap[p]) > tol + 1e-9:
                bad.append(f"{p}: {tid}={tmap[p]} vs 로컬={v}")
        if bad:
            rep.add(
                "C11",
                "WARN",
                tid,
                f"교차검증 {len(bad)}건 허용오차({tol}) 초과 — " + "; ".join(bad[:4]),
            )


def check_chart(ch: dict, root: Path, store: dict, rep: Report) -> None:
    cid = ch["id"]
    if ch.get("kind") not in KINDS:
        rep.add("C1", "FAIL", cid, f"kind {ch.get('kind')}")
    if ch.get("section") not in SECTIONS:
        rep.add("C1", "FAIL", cid, f"section {ch.get('section')}")
    xt = ch["x"]["type"]
    freq = XFREQ.get(xt)
    labels = ch["x"]["labels"]
    if freq is None:
        rep.add("C3", "FAIL", cid, f"x.type {xt}")
        return
    if freq != "C":
        bad = [x for x in labels if not period_ok(freq, x)]
        if bad:
            rep.add("C3", "FAIL", cid, f"x 라벨 형식 오류 {bad[:3]}")
        elif labels != sorted(set(labels)):
            rep.add("C3", "FAIL", cid, "x 라벨 중복·역순")
        elif freq in "MQA" and labels:
            idx = [period_index(freq, x) for x in labels]
            if idx != list(range(idx[0], idx[0] + len(idx))):
                rep.add("C3", "FAIL", cid, "월/분기/연 격자에 누락 라벨")
    ids = {y["id"]: y for y in ch["y"]}
    for y in ch["y"]:
        if not y.get("unit") or not isinstance(y.get("decimals"), int):
            rep.add("C5", "FAIL", cid, f"y축 {y.get('id')} 단위·자릿수 누락")
    concepts: dict[str, str] = {}
    for s in ch["series"]:
        k = s["key"]
        if s.get("freq") != freq:
            rep.add("C2", "FAIL", cid, f"{k} freq {s.get('freq')} ≠ {freq}")
        if len(s["values"]) != len(labels) or len(s["status"]) != len(labels):
            rep.add("C4", "FAIL", cid, f"{k} 길이 불일치")
        if s.get("axis") not in ids:
            rep.add("C5", "FAIL", cid, f"{k} axis {s.get('axis')}")
        if s.get("tier") not in TIERS:
            rep.add("C5", "FAIL", cid, f"{k} tier {s.get('tier')}")
        if not s.get("source"):
            rep.add("C5", "FAIL", cid, f"{k} source 누락")
        if s.get("color_role") not in COLOR_ROLES or s.get("gap") != "break":
            rep.add("C5", "FAIL", cid, f"{k} color_role/gap")
        if all(v is None for v in s["values"]):
            rep.add("C12", "WARN", cid, f"{k} 전 구간 결측")
        rec = store["series"].get(k)
        if rec:
            c = rec["concept"]
            if c in concepts and concepts[c] != k:
                rep.add("C9", "FAIL", cid, f"concept {c} 중복({concepts[c]}, {k})")
            concepts[c] = k
            if rec["tier"] == "llm_web" and ch.get("headline"):
                rep.add("C10", "WARN", cid, f"{k}: llm_web 계열이 headline 차트에 사용")
            lim = freshness_limit(c, rec["freq"])
            last = rec.get("last_period")
            if lim is not None and last and rec["freq"] in "DMQA":
                lag = _lag(rec["freq"], last, store["as_of"])
                if lag > lim:
                    unit = {"D": "일", "M": "개월", "Q": "분기", "A": "년"}[rec["freq"]]
                    rep.add(
                        "C8",
                        "WARN",
                        cid,
                        f"{k} 최신 {last} — 기준일 대비 {lag}{unit} 지연(한도 {lim})",
                    )
    # CSV 대조
    p = root / ch["data_csv"]
    csv_vals: dict[str, set[str]] = {}
    if not p.exists():
        rep.add("C6", "FAIL", cid, "CSV 없음")
    else:
        with p.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        if len(rows) != len(labels) * len(ch["series"]):
            rep.add("C6", "FAIL", cid, f"CSV 행수 {len(rows)} ≠ 격자×계열")
        jmap = {
            (lab, s["key"]): s["values"][i]
            for s in ch["series"]
            for i, lab in enumerate(labels)
            if i < len(s["values"])
        }
        mism = 0
        for r in rows:
            jv = jmap.get((r["date"], r["series_key"]))
            cv = float(r["value"]) if r["value"] else None
            if (jv is None) != (cv is None) or (jv is not None and abs(jv - cv) > 1e-9):
                mism += 1
            if cv is not None:
                csv_vals.setdefault(r["series_key"], set()).add(r["value"])
        if mism:
            rep.add("C6", "FAIL", cid, f"CSV↔JSON 값 불일치 {mism}건")
    # 제목·부제 수치
    allowed: set[str] = set()
    for s in ch["series"]:
        decs = {ids.get(s.get("axis"), {}).get("decimals", 1), s.get("decimals", 1)}
        for raw in csv_vals.get(s["key"], set()):
            for d in decs:
                allowed.add(fmt(float(raw), d).replace(",", ""))
    for field in ("title", "subtitle"):
        for tok in title_numbers(ch.get(field, "")):
            if tok not in allowed and tok.lstrip("-") not in allowed:
                rep.add("C7", "FAIL", cid, f"{field} 수치 '{tok}'가 CSV 값에 없음")


def _recalc(op: str, a, b, kind: str | None = None):
    if a is None or b is None:
        return None
    if op == "auto":
        op = "diff_bp" if kind == "bp" else "pct"
    if op == "diff":
        return a - b
    if op == "diff_bp":
        return (a - b) * 100
    if op == "pct":
        return (a / b - 1) * 100 if b else None
    raise ValueError(op)


def check_table(t: dict, rep: Report) -> None:
    tid = t.get("id", "?")
    cols = {c["key"]: c for c in t.get("columns", [])}
    for c in t.get("columns", []):
        missing = [
            k
            for k in ("key", "label", "unit", "decimals", "signed", "bold")
            if k not in c
        ]
        if missing:
            rep.add("T2", "FAIL", tid, f"열 {c.get('key')} 메타 누락 {missing}")
    for chk in t.get("checks", []):
        col = cols.get(chk["col"])
        dec = col["decimals"] if col else 2
        tol = 0.5 * 10 ** (-dec) + 1e-6
        bad = 0
        for r in t["rows"]:
            exp = _recalc(
                chk["op"],
                r.get(chk["a"]),
                r.get(chk["b"]),
                r.get(chk.get("kind_col", ""), None),
            )
            got = r.get(chk["col"])
            if exp is None and got is None:
                continue
            if (exp is None) != (got is None) or abs(exp - got) > tol:
                bad += 1
        if bad:
            rep.add("T1", "FAIL", tid, f"{chk['col']} 재계산 불일치 {bad}행")


def validate(root: Path) -> dict:
    root = Path(root)
    data = root / "data"
    store = json.loads((data / "series_store.json").read_text(encoding="utf-8"))
    cp = json.loads((data / "chart_pack.json").read_text(encoding="utf-8"))
    tp_path = data / "table_pack.json"
    tp = json.loads(tp_path.read_text(encoding="utf-8")) if tp_path.exists() else {}
    rep = Report()
    check_store(store, rep)
    n_det = n_all = 0
    for ch in cp["charts"]:
        check_chart(ch, root, store, rep)
        for s in ch["series"]:
            n_all += 1
            n_det += s.get("tier") != "llm_web"
    for t in tp.get("tables", []):
        check_table(t, rep)
    n_ch, n_tb = len(cp["charts"]), len(tp.get("tables", []))
    if n_ch < 20:
        rep.add("P1", "WARN", "chart_pack", f"차트 {n_ch}개 < 20")
    if n_tb < 8:
        rep.add("P1", "WARN", "table_pack", f"표 {n_tb}개 < 8")
    ratio = n_det / n_all if n_all else 0.0
    if ratio < 0.8:
        rep.add("P1", "WARN", "chart_pack", f"결정론 등급 비율 {ratio:.0%} < 80%")
    for s in cp.get("skipped", []):
        rep.add("P1", "WARN", s["id"], f"차트 생략: {s['reason']}")
    doc = {
        "status": rep.status,
        "as_of": store["as_of"],
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "counts": {
            "series": len(store["series"]),
            "charts": n_ch,
            "tables": n_tb,
            "deterministic_ratio": round(ratio, 3),
            "FAIL": sum(i["level"] == "FAIL" for i in rep.items),
            "WARN": sum(i["level"] == "WARN" for i in rep.items),
        },
        "items": rep.items,
    }
    (data / "validation.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="validate_pack")
    ap.add_argument("--root", required=True)
    a = ap.parse_args(argv)
    doc = validate(Path(a.root))
    print(f"{doc['status']} {doc['counts']}")
    for i in doc["items"]:
        print(f"  {i['level']:4} {i['rule']:3} {i['target']}: {i['msg']}")
    return 1 if doc["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
