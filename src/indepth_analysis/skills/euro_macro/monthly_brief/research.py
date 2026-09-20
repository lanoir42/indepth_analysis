"""Sonnet 웹리서치·시계열 수집 러너.

축별 `claude -p` 서브프로세스(세션별 WebSearch 예산).

    M=indepth_analysis.skills.euro_macro.monthly_brief.research
    uv run python -m $M --root reports/euro_macro/monthly_brief/2026-08 \
        --month 2026-08 --as-of 2026-09-10 --axes N02 N03 --series S1 S2 S3
    uv run python -m $M --root ... --axes N01           # ECB 회의 이후 단독 실행

산출: ``{root}/research/{axis}.md``(표준출력), ``{root}/data/series_{Sx}.json``
(코드펜스 JSON 파싱), 로그 ``{root}/_work/logs/{axis}.err``.
기존 산출이 있으면 건너뜀.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import hashlib
import re
from datetime import date
from pathlib import Path

from indepth_analysis.skills.euro_macro.monthly_brief import prompts as pr

MODEL = "sonnet"
MAX_CONCURRENCY = 8
TIMEOUT_S = 1800


def _month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{y}년 {int(m)}월"


def _window(month: str, as_of: str) -> str:
    y, m = month.split("-")
    return f"{y}-{m}-01 ~ {as_of}"


def build_axis_prompt(axis_key: str, month: str, as_of: str, known: str) -> str:
    spec = pr.RESEARCH_AXES[axis_key]
    head = pr.RESEARCH_HEADER.format(
        as_of=as_of,
        window=_window(month, as_of),
        month_label=_month_label(month),
        known=known,
    )
    body = (
        f"\n## 축: {axis_key} — {spec['title']}\n\n"
        f"## 조사 질문\n{spec['questions']}\n\n"
        f"## 검색 예산 배분 안내\n{spec['budget']}\n"
    )
    return head + body


def build_series_prompt(series_key: str, as_of: str) -> str:
    return pr.SERIES_HEADER.format(as_of=as_of) + "\n" + pr.SERIES_AGENTS[series_key]


async def _run_claude(
    prompt: str, out_md: Path, err: Path, sem: asyncio.Semaphore
) -> int:
    async with sem:
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


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _completed(output, prompt, receipt):
    try:
        state = json.loads(receipt.read_text())
        return (state.get("prompt") == _digest(prompt) and state.get("model") == MODEL
                and state.get("output") == _digest(output.read_text()))
    except (OSError, ValueError):
        return False


def _save_completion(output, prompt, receipt):
    receipt.write_text(json.dumps({"prompt": _digest(prompt), "model": MODEL,
                                   "output": _digest(output.read_text())}))


async def run(
    root: Path,
    month: str,
    as_of: str,
    axes: list[str],
    series: list[str],
    known_path: Path | None,
    suffix: str = "",
) -> dict[str, int]:
    research_dir = root / "research"
    data_dir = root / "data"
    logs = root / "_work" / "logs"
    for d in (research_dir, data_dir, logs):
        d.mkdir(parents=True, exist_ok=True)
    known = (
        known_path.read_text(encoding="utf-8")
        if known_path and known_path.exists()
        else pr.KNOWN_FACTS_FALLBACK
    )
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    tasks: dict[str, asyncio.Task] = {}
    completions = {}
    for key in axes:
        full = next((k for k in pr.RESEARCH_AXES if k.startswith(key)), None)
        if not full:
            raise SystemExit(f"unknown axis {key}")
        name = f"{full}{suffix}"
        out = research_dir / f"{name}.md"
        prompt = build_axis_prompt(full, month, as_of, known)
        receipt = logs / f"{name}.complete.json"
        if _completed(out, prompt, receipt):
            print(f"skip {name} (validated receipt)")
            continue
        completions[name] = (out, prompt, receipt)
        receipt.unlink(missing_ok=True)
        (logs / f"{name}.prompt.txt").write_text(prompt, encoding="utf-8")
        tasks[name] = asyncio.create_task(
            _run_claude(prompt, out, logs / f"{name}.err", sem)
        )
    for key in series:
        full = next((k for k in pr.SERIES_AGENTS if k.startswith(key)), None)
        if not full:
            raise SystemExit(f"unknown series agent {key}")
        out = research_dir / f"{full}.md"
        prompt = build_series_prompt(full, as_of)
        destination = data_dir / f"series_{full}.json"
        receipt = logs / f"{full}.complete.json"
        if _completed(destination, prompt, receipt):
            print(f"skip {full} (validated receipt)")
            continue
        completions[full] = (destination, prompt, receipt)
        receipt.unlink(missing_ok=True)
        (logs / f"{full}.prompt.txt").write_text(prompt, encoding="utf-8")
        tasks[full] = asyncio.create_task(
            _run_claude(prompt, out, logs / f"{full}.err", sem)
        )
    results: dict[str, int] = {}
    for key, t in tasks.items():
        rc = await t
        results[key] = rc
        if key.startswith("S") and rc == 0:
            parsed = parse_series_json((research_dir / f"{key}.md").read_text("utf-8"))
            if parsed is not None:
                (data_dir / f"series_{key}.json").write_text(
                    json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            else:
                results[key] = 65  # EX_DATAERR
        if results[key] == 0:
            output, prompt, receipt = completions[key]
            if not output.exists() or not output.read_text().strip():
                results[key] = 65
            else:
                _save_completion(output, prompt, receipt)
        print(f"{key}: exit={results[key]}")
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--as-of", default=date.today().isoformat())
    ap.add_argument("--axes", nargs="*", default=[])
    ap.add_argument("--series", nargs="*", default=[])
    ap.add_argument("--known", default=None, help="재조사 금지 사실 .md 경로")
    ap.add_argument("--suffix", default="", help="산출 파일명 접미 (예 _spot)")
    a = ap.parse_args()
    res = asyncio.run(
        run(
            Path(a.root),
            a.month,
            a.as_of,
            a.axes,
            a.series,
            Path(a.known) if a.known else None,
            a.suffix,
        )
    )
    return 0 if all(v == 0 for v in res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
