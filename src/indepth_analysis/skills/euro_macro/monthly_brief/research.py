"""Sonnet 웹리서치·웹 시계열·보충 리서치 러너 (v3).

축별 `claude -p` 서브프로세스(세션별 WebSearch 예산) 또는 ``report_cli`` 폴백 경로.
회차 정보는 전부 ``ROOT/edition.json``에서 읽는다(월 하드코딩 없음).

    M=indepth_analysis.skills.euro_macro.monthly_brief.research
    uv run python -m $M --root reports/euro_macro/monthly_brief/2026-09 \\
        --axes R01 R06 --web W1 W2 [--gaps ROOT/_work/gaps_r1.json] [--dry-run]

산출
- 리서치 축: ``ROOT/research/<AXIS>[_<phase>].md`` (phase=preview면 접미 없음)
- 웹 시계열: 원문 ``ROOT/research/<KEY>[_<phase>].md``
  + ``ROOT/data/web_series_<KEY>.json``
- 보충 리서치: ``ROOT/research/G_<round>_<n>[_<phase>].md`` (질문 ≤6개당 1세션)
- 로그·프롬프트·완료 영수증: ``ROOT/_work/logs/<name>.{prompt.txt,err,complete.json}``

입력(없으면 자리표시자로 진행)
- ``ROOT/data/facts.md`` — 알려진 사실(재조사 금지)
- ``ROOT/sections/<GROUP>.md`` — BI 스캐폴드(축별 관련 그룹을 ~6k자로 잘라 주입)

완료 영수증(프롬프트·모델·산출 해시)이 유효하면 재실행 시 건너뛴다.
v2 호출부(``__init__.run_stages``)를 위해 ``run()``(v2 시그니처)과
``pr``(= prompts_v2)을 남겨 둔다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path

from indepth_analysis.skills.euro_macro.monthly_brief import prompts as p3
from indepth_analysis.skills.euro_macro.monthly_brief import prompts_v2 as pr
from indepth_analysis.skills.euro_macro.monthly_brief.edition import (
    Edition,
    load_edition,
)

MODEL = "sonnet"
MAX_CONCURRENCY = 8
TIMEOUT_S = 1800
FACTS_MAX_CHARS = 15000
BI_CONTEXT_MAX_CHARS = 6000
GAP_BATCH = 6


# ---------------------------------------------------------------------------
# 입력 블록
# ---------------------------------------------------------------------------


def load_known(root: Path) -> str:
    """``data/facts.md``를 잘라 반환. 없으면 빈 문자열(→ 프롬프트 자리표시자)."""
    f = root / "data" / "facts.md"
    if not f.exists():
        return ""
    text = f.read_text(encoding="utf-8").strip()
    if len(text) > FACTS_MAX_CHARS:
        cut = text.rfind("\n", 0, FACTS_MAX_CHARS)
        text = text[: cut if cut > 0 else FACTS_MAX_CHARS] + "\n- …(facts.md 이하 생략)"
    return text


_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    return text[: cut if cut > 0 else limit] + "\n…(이하 생략)"


def bi_context(
    root: Path, groups: tuple[str, ...], limit: int = BI_CONTEXT_MAX_CHARS
) -> str:
    """``sections/<GROUP>.md`` 스캐폴드를 그룹별 균등 예산으로 잘라 합친다."""
    found: list[tuple[str, str]] = []
    for g in groups:
        f = root / "sections" / f"{g}.md"
        if f.exists():
            raw = _COMMENT.sub("", f.read_text(encoding="utf-8"))
            raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
            if raw:
                found.append((g, raw))
    if not found:
        return ""
    per = max(800, limit // len(found))
    return "\n\n".join(f"### BI 그룹 {g}\n{_clip(t, per)}" for g, t in found)


# ---------------------------------------------------------------------------
# 모델 호출
# ---------------------------------------------------------------------------


async def _run_claude(
    prompt: str, out_md: Path, err: Path, sem: asyncio.Semaphore
) -> int:
    async with sem:
        from indepth_analysis.report_cli import ReportCLIError, acomplete, enabled

        if enabled():
            try:
                text = await acomplete(prompt, tier=MODEL, timeout=TIMEOUT_S, web=True)
            except ReportCLIError as error:
                err.write_text(f"report_inference:{error}\nexit=1\n", encoding="utf-8")
                return 1
            out_md.write_text(text, encoding="utf-8")
            err.write_text("exit=0\n", encoding="utf-8")
            return 0
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            prompt,
            "--model",
            MODEL,
            "--allowedTools",
            "WebSearch WebFetch",
            "--output-format",
            "text",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, er = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            err.write_text("timeout\nexit=124\n", encoding="utf-8")
            return 124
        if proc.returncode == 0:
            out_md.write_text(out.decode("utf-8", "replace"), encoding="utf-8")
        err.write_text(
            er.decode("utf-8", "replace") + f"\nexit={proc.returncode}\n",
            encoding="utf-8",
        )
        return proc.returncode or 0


_JSON_FENCE = re.compile(r"```json\s*(\{.*\})\s*```", re.DOTALL)


def parse_series_json(text: str) -> dict | None:
    mo = _JSON_FENCE.search(text)
    raw = mo.group(1) if mo else text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _completed(output: Path, prompt: str, receipt: Path) -> bool:
    try:
        state = json.loads(receipt.read_text())
        return (
            state.get("prompt") == _digest(prompt)
            and state.get("model") == MODEL
            and state.get("output") == _digest(output.read_text())
        )
    except (OSError, ValueError):
        return False


def _save_completion(output: Path, prompt: str, receipt: Path) -> None:
    receipt.write_text(
        json.dumps(
            {
                "prompt": _digest(prompt),
                "model": MODEL,
                "output": _digest(output.read_text()),
            }
        )
    )


# ---------------------------------------------------------------------------
# 작업 계획 (v3)
# ---------------------------------------------------------------------------


def phase_suffix(ed: Edition) -> str:
    return "" if ed.phase == "preview" else f"_{ed.phase}"


def _gap_round(path: Path) -> str:
    stem = path.stem  # gaps_r1
    return stem.split("_", 1)[1] if stem.startswith("gaps_") and "_" in stem else stem


def plan_jobs(
    root: Path,
    ed: Edition,
    axes: list[str],
    web: list[str],
    gaps: Path | None,
) -> list[dict]:
    """실행할 작업 목록. 작업 키: name, prompt, raw(원문), dest(영수증 대상), kind."""
    known = load_known(root)
    sfx = phase_suffix(ed)
    jobs: list[dict] = []
    for key in axes:
        full = p3.resolve_axis(key)
        prompt = p3.build_axis_prompt(
            full, ed, known, bi_context(root, p3.AXIS_GROUPS[full])
        )
        raw = root / "research" / f"{full}{sfx}.md"
        jobs.append(
            {
                "name": f"{full}{sfx}",
                "prompt": prompt,
                "raw": raw,
                "dest": raw,
                "kind": "axis",
            }
        )
    for key in web:
        full = p3.resolve_web(key)
        prompt = p3.build_web_series_prompt(full, ed, known)
        jobs.append(
            {
                "name": f"{full}{sfx}",
                "prompt": prompt,
                "raw": root / "research" / f"{full}{sfx}.md",
                "dest": root / "data" / f"web_series_{full}.json",
                "kind": "web",
            }
        )
    if gaps is not None:
        items = json.loads(Path(gaps).read_text(encoding="utf-8"))
        rid = _gap_round(Path(gaps))
        for i in range(0, len(items), GAP_BATCH):
            n = i // GAP_BATCH + 1
            prompt = p3.build_gap_prompt(rid, n, items[i : i + GAP_BATCH], ed, known)
            raw = root / "research" / f"G_{rid}_{n}{sfx}.md"
            jobs.append(
                {
                    "name": f"G_{rid}_{n}{sfx}",
                    "prompt": prompt,
                    "raw": raw,
                    "dest": raw,
                    "kind": "gap",
                }
            )
    return jobs


async def run_v3(
    root: Path,
    axes: list[str],
    web: list[str],
    gaps: Path | None = None,
    dry_run: bool = False,
    ed: Edition | None = None,
) -> dict[str, int]:
    ed = ed or load_edition(root)
    logs = root / "_work" / "logs"
    for d in (root / "research", root / "data", logs):
        d.mkdir(parents=True, exist_ok=True)
    jobs = plan_jobs(root, ed, axes, web, gaps)
    results: dict[str, int] = {}
    if dry_run:
        for j in jobs:
            f = logs / f"{j['name']}.prompt.txt"
            f.write_text(j["prompt"], encoding="utf-8")
            results[j["name"]] = 0
            print(f"dry-run {j['name']}: {len(j['prompt'])} chars → {f}")
        return results
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    tasks: dict[str, tuple[dict, asyncio.Task]] = {}
    for j in jobs:
        receipt = logs / f"{j['name']}.complete.json"
        if _completed(j["dest"], j["prompt"], receipt):
            print(f"skip {j['name']} (validated receipt)")
            continue
        receipt.unlink(missing_ok=True)
        (logs / f"{j['name']}.prompt.txt").write_text(j["prompt"], encoding="utf-8")
        tasks[j["name"]] = (
            j,
            asyncio.create_task(
                _run_claude(j["prompt"], j["raw"], logs / f"{j['name']}.err", sem)
            ),
        )
    for name, (j, t) in tasks.items():
        rc = await t
        if rc == 0 and j["kind"] == "web":
            parsed = parse_series_json(j["raw"].read_text("utf-8"))
            if parsed is None:
                rc = 65  # EX_DATAERR
            else:
                j["dest"].write_text(
                    json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        if rc == 0:
            dest = j["dest"]
            if not dest.exists() or not dest.read_text().strip():
                rc = 65
            else:
                _save_completion(dest, j["prompt"], logs / f"{name}.complete.json")
        results[name] = rc
        print(f"{name}: exit={rc}")
    return results


# ---------------------------------------------------------------------------
# v2 호환 (monthly_brief.__init__.run_stages가 사용) — prompts_v2 상수 기반
# ---------------------------------------------------------------------------


def _v2_window(month: str, as_of: str) -> str:
    y, m = month.split("-")
    return f"{y}-{m}-01 ~ {as_of}"


def build_axis_prompt(axis_key: str, month: str, as_of: str, known: str) -> str:
    """v2 축 프롬프트(보존용)."""
    spec = pr.RESEARCH_AXES[axis_key]
    y, m = month.split("-")
    head = pr.RESEARCH_HEADER.format(
        as_of=as_of,
        window=_v2_window(month, as_of),
        month_label=f"{y}년 {int(m)}월",
        known=known,
    )
    return head + (
        f"\n## 축: {axis_key} — {spec['title']}\n\n"
        f"## 조사 질문\n{spec['questions']}\n\n"
        f"## 검색 예산 배분 안내\n{spec['budget']}\n"
    )


async def run(
    root: Path,
    month: str,
    as_of: str,
    axes: list[str],
    series: list[str],
    known_path: Path | None,
    suffix: str = "",
) -> dict[str, int]:
    """v2 시그니처 실행기(N0x 축·S 시계열). 신규 회차는 ``run_v3`` 사용."""
    research_dir, data_dir, logs = (
        root / "research",
        root / "data",
        root / "_work" / "logs",
    )
    for d in (research_dir, data_dir, logs):
        d.mkdir(parents=True, exist_ok=True)
    known = (
        known_path.read_text(encoding="utf-8")
        if known_path and known_path.exists()
        else pr.KNOWN_FACTS_FALLBACK
    )
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    jobs: list[tuple[str, str, Path, Path, bool]] = []
    for key in axes:
        full = next((k for k in pr.RESEARCH_AXES if k.startswith(key)), None)
        if not full:
            raise SystemExit(f"unknown axis {key}")
        out = research_dir / f"{full}{suffix}.md"
        jobs.append(
            (
                f"{full}{suffix}",
                build_axis_prompt(full, month, as_of, known),
                out,
                out,
                False,
            )
        )
    for key in series:
        full = next((k for k in pr.SERIES_AGENTS if k.startswith(key)), None)
        if not full:
            raise SystemExit(f"unknown series agent {key}")
        prompt = pr.SERIES_HEADER.format(as_of=as_of) + "\n" + pr.SERIES_AGENTS[full]
        jobs.append(
            (
                full,
                prompt,
                research_dir / f"{full}.md",
                data_dir / f"series_{full}.json",
                True,
            )
        )
    tasks = {}
    for name, prompt, raw, dest, is_series in jobs:
        receipt = logs / f"{name}.complete.json"
        if _completed(dest, prompt, receipt):
            print(f"skip {name} (validated receipt)")
            continue
        receipt.unlink(missing_ok=True)
        (logs / f"{name}.prompt.txt").write_text(prompt, encoding="utf-8")
        tasks[name] = (
            prompt,
            raw,
            dest,
            is_series,
            asyncio.create_task(_run_claude(prompt, raw, logs / f"{name}.err", sem)),
        )
    results: dict[str, int] = {}
    for name, (prompt, raw, dest, is_series, t) in tasks.items():
        rc = await t
        if rc == 0 and is_series:
            parsed = parse_series_json(raw.read_text("utf-8"))
            if parsed is None:
                rc = 65
            else:
                dest.write_text(
                    json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        if rc == 0:
            if not dest.exists() or not dest.read_text().strip():
                rc = 65
            else:
                _save_completion(dest, prompt, logs / f"{name}.complete.json")
        results[name] = rc
        print(f"{name}: exit={rc}")
    return results


# ---------------------------------------------------------------------------
# CLI (v3)
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="월간 유럽 매크로 v3 리서치 러너")
    ap.add_argument("--root", required=True, help="회차 루트(edition.json 위치)")
    ap.add_argument("--axes", nargs="*", default=[], help="R01 … R12 (전체 키도 허용)")
    ap.add_argument("--web", nargs="*", default=[], help="W1 W2")
    ap.add_argument("--gaps", default=None, help="ROOT/_work/gaps_<round>.json")
    ap.add_argument(
        "--dry-run", action="store_true", help="프롬프트만 기록, 모델 호출 없음"
    )
    ap.add_argument("--list", action="store_true", help="축 목록 출력")
    a = ap.parse_args()
    if a.list:
        print(p3.axis_catalog())
        return 0
    res = asyncio.run(
        run_v3(
            Path(a.root),
            a.axes,
            a.web,
            Path(a.gaps) if a.gaps else None,
            a.dry_run,
        )
    )
    return 0 if all(v == 0 for v in res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
