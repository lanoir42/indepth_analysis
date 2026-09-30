"""v3 WP1 문서 카드 — Sonnet이 BI 문서 1건을 한 번 읽고 JSON 카드로 고정한다.

    M=indepth_analysis.skills.euro_macro.monthly_brief.cards
    uv run python -m $M run --month 2026-09 [--limit N] [--concurrency 6]

- 대상 = 세션의 ``uncarded``(중복은 원본 카드를 재사용, 조각은 카드 없음).
- 저장 ``references/mendeley_europe/cards/<sha16>.json`` (월 간 재사용, 덮어쓰지 않음).
- 검증: ``contract.Card`` 스키마(실패 시 1회 재시도) + **수치 대조**(key_numbers
  값이 원문 숫자 집합에 없으면 1회 재요청, 그래도 없으면 ``unverified_numbers``로
  격리 — 카드 본체에는 원문에 있는 수치만 남긴다).
- 호출: ``report_cli.enabled()``면 ``acomplete(tier='sonnet', web=False)``,
  아니면 ``claude -p --model sonnet --output-format text``(도구 없음).
- 로그 ``ROOT/_work/logs/cards.log``. 끝나면 스캐폴드를 재실행한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from indepth_analysis.skills.euro_macro.monthly_brief import intake
from indepth_analysis.skills.euro_macro.monthly_brief.contract import (
    CARD_VERSION,
    GROUPS,
    validate_card,
)
from indepth_analysis.skills.euro_macro.monthly_brief.edition import (
    BASE_DIR,
    load_edition,
)

MODEL = "sonnet"
TIMEOUT_S = 420
MAX_CHARS = 12_000
DEFAULT_CONCURRENCY = 6

_EU_KW = re.compile(
    r"\bECB\b|euro[- ]?area|eurozone|\bEU\b|Europe|German|France|French|Ital|Spain"
    r"|Spanish|\bUK\b|\bBOE\b|Britain|gilt|Bund|Lagarde|Merz|Macron|HICP|\bSNB\b"
    r"|Swiss|Nordic|Sweden|Norway|Poland|Netherlands|\bTTF\b|natural gas",
    re.IGNORECASE,
)
_ITEM = re.compile(r"^(\d{1,2})\.\s+\S")

PROMPT = """당신은 유럽 거시경제 리서치 사서다.
아래 Bloomberg Intelligence(Bloomberg Economics) 문서 1건을 읽고
**JSON 객체 하나만** 출력한다. 설명·코드펜스·머리말 금지.

## 문서 메타(결정론 파싱, 수정 금지)
- 제목: {title}
- 발행: {published_at}
- 계열: {series} · 지역: {geo} · 저자: {author}
- 규칙 기반 후보 그룹: {groups}
{excerpt_note}
## 출력 스키마
{{
 "title_ko": "제목의 한국어 번역(명사구, 60자 이내)",
 "groups": ["{group_list} 중 1~4개, 중심 주제 순서(첫 원소=1차 그룹)"],
 "summary_ko": ["불릿 3~5개. 각 1~2문장, 한국어 개조식(~임·~음 종결).
   문서의 핵심 판단·근거·전망. 모음물이면 유럽(유로존·ECB·EU·영국·
   유럽 각국·에너지) 관련 내용을 우선"],
 "key_numbers": [{{"metric": "지표명(영문 약칭 가능)",
   "geo": "EA|DE|FR|IT|ES|UK|EU|US|CN|JP|GLOBAL 등",
   "period": "YYYY-MM 또는 YYYY-Qn 또는 YYYY", "value": 숫자,
   "unit": "% YoY|% QoQ|%|bp|index|EUR bn|USD/bbl 등",
   "kind": "actual|forecast|consensus|estimate", "note": "짧은 맥락(선택)"}}],
 "claims": [{{"claim_ko": "BI의 주장·판단 한 문장",
   "stance": "hawkish|dovish|upside|downside|neutral",
   "horizon": "예: 2026-12 회의, 4Q26, 2027", "confidence": "high|mid|low"}}],
 "forecasts": [{{"variable": "DFR|HICP|GDP 등", "value": 숫자 또는 짧은 문자열,
   "by": "시점", "source_view": "BI 또는 시장·컨센서스 등 출처"}}],
 "politics": [{{"country": "FR|DE|IT|ES|UK|EU 등", "actors": ["실명"],
   "event": "사건·쟁점 한국어 요약", "date": "YYYY-MM-DD 또는 빈 문자열"}}],
 "importance": 1~5
}}

## 규칙
1. key_numbers는 **본문에 숫자로 적힌 값만** 옮긴다(최대 10개).
   계산·환산·반올림·추정 금지. value는 본문 숫자 그대로
   (예: "2.50%" → 2.5, "fell 0.2%" → -0.2, "25 bps" → 25). 유럽 관련 수치 우선.
2. 본문에 없는 사실·수치·인명을 만들지 않는다. forecasts도 본문에 명시된 전망만.
3. politics는 정치 행위자·선거·의회·예산·정당 사건이 있을 때만(없으면 []).
   인명은 본문 표기 그대로.
4. claims 2~5개. stance는 통화정책이면 hawkish/dovish,
   성장·물가 방향이면 upside/downside.
5. importance: 5=ECB 결정·유로존 핵심 지표·주요국 정치 위기,
   4=유럽 국가 핵심 지표·정책, 3=유럽 관련 분석,
   2=유럽 비중이 작은 글로벌 모음물, 1=유럽과 무관.
6. 문자열 안의 큰따옴표는 이스케이프한다. JSON 외 텍스트를 쓰지 않는다.
{retry_note}
## 문서 본문
{body}
"""


# ---------------------------------------------------------------------------
# 본문 발췌·수치 대조
# ---------------------------------------------------------------------------


def excerpt(body: str, limit: int = MAX_CHARS) -> tuple[str, bool]:
    """≤limit자 본문. 모음물(번호 항목)은 1번 항목 + 유럽 관련 항목 우선."""
    if len(body) <= limit:
        return body, False
    lines = body.splitlines()
    items: list[list[str]] = [[]]
    for ln in lines:
        if _ITEM.match(ln) and len(items[-1]) > 0:
            items.append([])
        items[-1].append(ln)
    if len(items) <= 2:
        return body[:limit], True
    texts = ["\n".join(it) for it in items]
    head, rest = texts[0], list(enumerate(texts[1:], 1))
    scored = sorted(rest, key=lambda kv: (-len(_EU_KW.findall(kv[1])), kv[0]))
    chosen = [0]
    used = len(head)
    for idx, t in scored:
        if used + len(t) + 1 > limit:
            continue
        if len(_EU_KW.findall(t)) == 0 and used > limit * 0.6:
            continue
        chosen.append(idx)
        used += len(t) + 1
    out = "\n".join(texts[i] for i in sorted(chosen))
    return out[:limit], True


_NUM = re.compile(r"(?<![\w.])[-−–]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-−–]?\d+(?:\.\d+)?")


def numbers_in(text: str) -> set[float]:
    out: set[float] = set()
    for tok in _NUM.findall(text):
        t = tok.replace(",", "").replace("−", "-").replace("–", "-")
        try:
            out.add(abs(float(t)))
        except ValueError:
            continue
    return out


def unverified(card: dict, source: str) -> list[dict]:
    nums = numbers_in(source)
    bad = []
    for kn in card.get("key_numbers", []):
        try:
            v = abs(float(kn.get("value")))
        except (TypeError, ValueError):
            bad.append(kn)
            continue
        if not any(abs(v - n) < 1e-9 for n in nums):
            bad.append(kn)
    return bad


def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    s, e = t.find("{"), t.rfind("}")
    if s < 0 or e <= s:
        raise ValueError("JSON 객체 없음")
    return json.loads(t[s : e + 1])


def build_prompt(doc: intake.Doc, retry_note: str = "") -> tuple[str, str]:
    body, cut = excerpt(doc.body)
    note = (
        f"- 본문은 전체 {doc.chars:,}자 중 {len(body):,}자 발췌(모음물은 유럽 관련 "
        "항목 우선). 발췌 밖 내용을 추정하지 않는다.\n"
        if cut
        else ""
    )
    prompt = PROMPT.format(
        title=doc.title,
        published_at=doc.published_at or "미상",
        series=doc.series,
        geo=doc.geo,
        author=doc.author or "미상",
        groups=", ".join(doc.groups),
        group_list="|".join(GROUPS),
        excerpt_note=note,
        retry_note=retry_note,
        body=body,
    )
    return prompt, body


def assemble(doc: intake.Doc, raw: dict, model: str) -> dict:
    """모델 출력 + 결정론 메타 → 카드 dict(검증 전)."""
    card = {
        "sha16": doc.sha16,
        "title_ko": raw.get("title_ko", ""),
        "published_at": doc.published_at,
        "series": doc.series,
        "geo": doc.geo,
        "groups": [g for g in raw.get("groups", []) if g in GROUPS][:4]
        or doc.groups[:4],
        "summary_ko": raw.get("summary_ko", []),
        "key_numbers": raw.get("key_numbers", []) or [],
        "claims": raw.get("claims", []) or [],
        "forecasts": raw.get("forecasts", []) or [],
        "politics": raw.get("politics", []) or [],
        "importance": raw.get("importance"),
        "card_model": model,
        "card_version": CARD_VERSION,
        "title_en": doc.title,
        "author": doc.author,
        "source_md": doc.md_path,
        "carded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    for kn in card["key_numbers"]:
        if isinstance(kn, dict):
            for k in ("geo", "period", "unit", "note"):
                if kn.get(k) is None:
                    kn[k] = ""
    for c in card["politics"]:
        if isinstance(c, dict) and c.get("date") is None:
            c["date"] = ""
    for f in card["forecasts"]:
        if isinstance(f, dict):
            f.setdefault("by", "")
            f.setdefault("source_view", "BI")
            if f.get("by") is None:
                f["by"] = ""
    return card


# ---------------------------------------------------------------------------
# 모델 호출
# ---------------------------------------------------------------------------


async def call_model(prompt: str) -> tuple[str, str]:
    """(text, model_label)."""
    from indepth_analysis.report_cli import ReportCLIError, acomplete, enabled

    if enabled():
        try:
            out = await acomplete(prompt, tier=MODEL, timeout=TIMEOUT_S, web=False)
        except ReportCLIError as e:
            raise RuntimeError(f"report_cli:{e}") from e
        prov = getattr(out, "provider", "claude")
        mdl = getattr(out, "model", MODEL)
        return str(out), (mdl if prov == "claude" else f"{prov}:{mdl}")
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        "--model",
        MODEL,
        "--output-format",
        "text",
        "--tools",
        "",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")), timeout=TIMEOUT_S
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("timeout") from None
    if proc.returncode:
        raise RuntimeError(f"exit={proc.returncode}: {err.decode()[:200]}")
    return out.decode("utf-8", "replace"), MODEL


class CardLog:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **kw) -> None:
        kw = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **kw}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n")


async def card_one(
    doc: intake.Doc, out_dir: Path, log: CardLog, sem: asyncio.Semaphore
) -> bool:
    async with sem:
        dest = out_dir / f"{doc.sha16}.json"
        if dest.exists():
            return True
        retry_note = ""
        last_err = ""
        card: dict | None = None
        body = ""
        for attempt in (1, 2):
            prompt, body = build_prompt(doc, retry_note)
            t0 = time.monotonic()
            try:
                text, model = await call_model(prompt)
            except RuntimeError as e:
                last_err = str(e)
                log.write(
                    sha16=doc.sha16,
                    attempt=attempt,
                    status="call_error",
                    error=last_err,
                    secs=round(time.monotonic() - t0, 1),
                )
                retry_note = ""
                continue
            secs = round(time.monotonic() - t0, 1)
            try:
                raw = parse_json(text)
                cand = assemble(doc, raw, model)
                validate_card(cand)
            except (ValueError, ValidationError) as e:
                last_err = str(e)[:600]
                log.write(
                    sha16=doc.sha16,
                    attempt=attempt,
                    status="invalid",
                    model=model,
                    secs=secs,
                    prompt_chars=len(prompt),
                    out_chars=len(text),
                    error=last_err,
                )
                retry_note = (
                    "\n## 재시도 안내\n직전 출력이 스키마 검증에 실패했다: "
                    f"{last_err[:400]}\n"
                    "JSON 객체 하나만, 스키마 그대로 다시 출력한다.\n"
                )
                continue
            bad = unverified(cand, body)
            log.write(
                sha16=doc.sha16,
                attempt=attempt,
                status="ok",
                model=model,
                secs=secs,
                prompt_chars=len(prompt),
                out_chars=len(text),
                unverified=len(bad),
            )
            card = cand
            if bad and attempt == 1:
                vals = ", ".join(f"{b.get('metric')}={b.get('value')}" for b in bad)
                retry_note = (
                    "\n## 재시도 안내\n직전 출력의 key_numbers 중 "
                    f"다음 값은 본문 숫자와 일치하지 않는다: {vals}. "
                    "본문에 적힌 숫자 그대로 고치거나 빼고, "
                    "나머지 필드는 유지해 JSON 전체를 다시 출력한다.\n"
                )
                continue
            break
        if card is None:
            log.write(sha16=doc.sha16, status="failed", error=last_err, title=doc.title)
            return False
        bad = unverified(card, body)
        if bad:
            card["unverified_numbers"] = bad
            card["key_numbers"] = [k for k in card["key_numbers"] if k not in bad]
        card["text_excerpted"] = len(body) < doc.chars
        validate_card(card)
        tmp = dest.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(card, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        tmp.replace(dest)
        return True


async def run(
    month: str, *, limit: int | None, concurrency: int, repo_root: Path | None = None
) -> dict:
    repo_root = Path(repo_root or intake.REPO_ROOT)
    ed = load_edition(repo_root / BASE_DIR / month)
    session = intake.scaffold(ed, repo_root=repo_root)
    docs = intake.collect(ed, repo_root)
    by_sha: dict[str, intake.Doc] = {}
    for d in docs:
        by_sha.setdefault(d.sha16, d)
    targets = [by_sha[s] for s in session["uncarded"] if s in by_sha]
    if limit:
        targets = targets[:limit]
    out_dir = repo_root / intake.CARDS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    log = CardLog(repo_root / ed.root / "_work" / "logs" / "cards.log")
    log.write(status="run_start", targets=len(targets), concurrency=concurrency)
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(card_one(d, out_dir, log, sem) for d in targets))
    ok = sum(results)
    failed = [d.sha16 for d, r in zip(targets, results, strict=True) if not r]
    session = intake.scaffold(ed, repo_root=repo_root)
    log.write(status="run_end", ok=ok, failed=failed, uncarded=len(session["uncarded"]))
    return {
        "targets": len(targets),
        "ok": ok,
        "failed": failed,
        "uncarded_after": len(session["uncarded"]),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="monthly_brief.cards")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--month", required=True)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    a = ap.parse_args(argv)
    res = asyncio.run(run(a.month, limit=a.limit, concurrency=a.concurrency))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if not res["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
