# ruff: noqa: E501
"""파이프라인 토큰 사용량 리포트 — Claude Code 트랜스크립트 스캔 → 모델·역할별 토큰·API 정가 환산·플랜 스냅샷.

    M=indepth_analysis.skills.euro_macro.monthly_brief.usage_report
    uv run python -m $M --root reports/euro_macro/monthly_brief/2026-08 --phase preview \
        --since "2026-09-10T07:40:00+09:00" [--until ...] [--session 47e33594-...]

집계 원리
- `~/.claude/projects/<project-dir>/` 아래 `*.jsonl`(메인 세션·`claude -p` 세션), `subagents/agent-*.jsonl`,
  `workflows/**/*.jsonl`(팀 Noir) 중 수정시각이 창 안인 파일을 읽어 `type=assistant` 레코드의
  `message.usage`를 모델별로 합산. 스트리밍은 같은 `message.id`로 여러 레코드가 쌓이므로 id별 **최대값**으로 중복 제거.
- 가격: Anthropic 1차 API 정가(USD/MTok, 2026-06 캐시 기준) — Fable 5.1 10/50(캐시 읽기 0.25), Opus 5 5/25, Sonnet 5 2/10, Haiku 4.5 1/5.
  캐시 쓰기 = 입력×1.25, 캐시 읽기 = 입력×0.1(Fable은 $0.25/MTok). 구독(플랜) 과금이 아니라 **정가 환산치**.
- 플랜 스냅샷: Claude Code OAuth 사용량 엔드포인트를 조회(키체인 자격증명 사용, 토큰은 출력하지 않음). 실패 시 `/usage` 수동 확인 안내.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

PRICES: dict[str, tuple[float, float, float | None]] = {
    # key: (input, output, cache_read override per MTok)
    "fable": (10.0, 50.0, 0.25),
    "mythos": (10.0, 50.0, 0.25),
    "opus": (5.0, 25.0, None),
    "sonnet": (2.0, 10.0, None),
    "haiku": (1.0, 5.0, None),
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10
PROJECTS = Path.home() / ".claude" / "projects"


def _price(model: str) -> tuple[float, float, float]:
    m = model.lower()
    for k, (pi, po, cr) in PRICES.items():
        if k in m:
            return pi, po, cr if cr is not None else pi * CACHE_READ_MULT
    return 3.0, 15.0, 0.3


def cost(model: str, tin: int, tout: int, cw: int, cr: int) -> float:
    pi, po, pcr = _price(model)
    return (tin * pi + tout * po + cw * pi * CACHE_WRITE_MULT + cr * pcr) / 1e6


def _classify(path: Path, main_session: str | None) -> str:
    parts = path.parts
    if "workflows" in parts:
        return "workflow(팀 Noir Opus)"
    if "subagents" in parts:
        return "agent(Opus 다이제스트 등)"
    if main_session and path.stem == main_session:
        return "main(Fable 오케스트레이션)"
    return "claude -p(Sonnet 리서치)"


def scan(
    project_dir: Path, since: datetime, until: datetime, main_session: str | None
) -> dict:
    per_msg: dict[str, dict] = {}
    files = 0
    for p in project_dir.rglob("*.jsonl"):
        try:
            mt = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mt < since:
            continue
        files += 1
        kind = _classify(p, main_session)
        with p.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"usage"' not in line or '"assistant"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "assistant":
                    continue
                ts = rec.get("timestamp")
                if ts:
                    try:
                        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if t < since or t > until:
                            continue
                    except ValueError:
                        pass
                msg = rec.get("message") or {}
                u = msg.get("usage") or {}
                if not u:
                    continue
                mid = msg.get("id") or f"{p.name}:{rec.get('uuid')}"
                model = msg.get("model") or "unknown"
                label = rec.get("attributionAgent") or rec.get("agentId") or ""
                cur = per_msg.setdefault(
                    mid,
                    {
                        "model": model,
                        "kind": kind,
                        "label": label,
                        "file": p.name,
                        "in": 0,
                        "out": 0,
                        "cw": 0,
                        "cr": 0,
                    },
                )
                cur["in"] = max(cur["in"], int(u.get("input_tokens") or 0))
                cur["out"] = max(cur["out"], int(u.get("output_tokens") or 0))
                cur["cw"] = max(
                    cur["cw"], int(u.get("cache_creation_input_tokens") or 0)
                )
                cur["cr"] = max(cur["cr"], int(u.get("cache_read_input_tokens") or 0))
    agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"calls": 0, "in": 0, "out": 0, "cw": 0, "cr": 0, "usd": 0.0}
    )
    files_by_kind: dict[str, set] = defaultdict(set)
    for m in per_msg.values():
        a = agg[(m["kind"], m["model"])]
        a["calls"] += 1
        for k in ("in", "out", "cw", "cr"):
            a[k] += m[k]
        a["usd"] += cost(m["model"], m["in"], m["out"], m["cw"], m["cr"])
        files_by_kind[m["kind"]].add(m["file"])
    return {
        "files": files,
        "agg": agg,
        "files_by_kind": {k: len(v) for k, v in files_by_kind.items()},
        "messages": len(per_msg),
    }


def plan_snapshot() -> dict:
    """Claude Code OAuth 사용량 스냅샷(가능한 경우). 토큰은 반환·출력하지 않음."""
    out: dict = {"ok": False, "note": ""}
    try:
        raw = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "Claude Code-credentials",
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        cred = json.loads(raw).get("claudeAiOauth", {}) if raw else {}
        tok = cred.get("accessToken")
        out["subscription"] = cred.get("subscriptionType")
        out["tier"] = cred.get("rateLimitTier")
        if not tok:
            out["note"] = "키체인 OAuth 자격증명 없음 — Claude Code에서 /usage 로 확인"
            return out
        import requests

        r = requests.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {tok}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "claude-code-usage-report",
            },
            timeout=20,
        )
        if r.status_code != 200:
            out["note"] = (
                f"usage 엔드포인트 HTTP {r.status_code} — Claude Code에서 /usage 로 확인"
            )
            return out
        out["ok"] = True
        out["data"] = r.json()
    except Exception as exc:  # noqa: BLE001
        out["note"] = (
            f"스냅샷 실패: {type(exc).__name__} — Claude Code에서 /usage 로 확인"
        )
    return out


def _fmt(n: int) -> str:
    return (
        f"{n / 1e6:.2f}M" if n >= 1e6 else (f"{n / 1e3:.0f}k" if n >= 1e3 else str(n))
    )


def render(res: dict, snap: dict, phase: str, since: datetime, until: datetime) -> str:
    rows = sorted(res["agg"].items(), key=lambda kv: -kv[1]["usd"])
    tot = {"calls": 0, "in": 0, "out": 0, "cw": 0, "cr": 0, "usd": 0.0}
    lines = [
        f"# 토큰 사용량 리포트 — 유럽 매크로 월간 브리프 v2 ({phase})",
        "",
        f"- 집계 창: {since.astimezone().isoformat(timespec='minutes')} ~ {until.astimezone().isoformat(timespec='minutes')} (KST)",
        f"- 스캔 파일 {res['files']}개 · 고유 assistant 메시지 {res['messages']}건 · 종류별 파일 수 {res['files_by_kind']}",
        "- 환산 단가(USD/MTok): Fable 5.1 10/50(캐시R 0.25) · Opus 5 5/25 · Sonnet 5 2/10 · Haiku 4.5 1/5 · 캐시W ×1.25 · 캐시R ×0.1. **구독 과금이 아닌 API 정가 환산치**",
        "",
        "## 역할·모델별",
        "",
        "| 역할 | 모델 | 호출 | 입력 | 출력 | 캐시W | 캐시R | 환산 USD |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for (kind, model), a in rows:
        lines.append(
            f"| {kind} | {model} | {a['calls']} | {_fmt(a['in'])} | {_fmt(a['out'])} | {_fmt(a['cw'])} | {_fmt(a['cr'])} | {a['usd']:.2f} |"
        )
        for k in tot:
            tot[k] += a[k]
    lines.append(
        f"| **합계** | | {tot['calls']} | {_fmt(tot['in'])} | {_fmt(tot['out'])} | {_fmt(tot['cw'])} | {_fmt(tot['cr'])} | **{tot['usd']:.2f}** |"
    )
    by_model: dict[str, float] = defaultdict(float)
    for (_, model), a in rows:
        by_model[model] += a["usd"]
    lines += ["", "## 모델별 환산 비용", "", "| 모델 | USD | 비중 |", "|---|---:|---:|"]
    for m, v in sorted(by_model.items(), key=lambda kv: -kv[1]):
        lines.append(
            f"| {m} | {v:.2f} | {100 * v / tot['usd']:.0f}% |"
            if tot["usd"]
            else f"| {m} | {v:.2f} | - |"
        )
    lines += ["", "## 플랜 사용량 스냅샷", ""]
    if snap.get("subscription"):
        lines.append(
            f"- 구독: {snap.get('subscription')} · 요율 티어: {snap.get('tier')}"
        )
    if snap.get("ok"):
        d = snap["data"]
        lines += ["", "| 한도 창 | 소진율 | 리셋 시각(KST) |", "|---|---:|---|"]
        for key, name in (
            ("five_hour", "5시간"),
            ("seven_day", "7일(전체)"),
            ("seven_day_opus", "7일(Opus)"),
            ("seven_day_sonnet", "7일(Sonnet)"),
        ):
            v = d.get(key)
            if not v:
                continue
            reset = v.get("resets_at")
            try:
                reset_kst = (
                    datetime.fromisoformat(reset).astimezone().strftime("%m-%d %H:%M")
                    if reset
                    else "-"
                )
            except ValueError:
                reset_kst = reset or "-"
            lines.append(f"| {name} | {v.get('utilization', 0):.0f}% | {reset_kst} |")
        lines.append("")
        lines.append(
            "스냅샷은 실행 시각 기준. 파이프라인 전후 두 번 실행해 차이를 보면 이번 회차의 플랜 소비분이 나온다."
        )
    else:
        lines.append(f"- {snap.get('note') or '스냅샷 불가'}")
        lines.append(
            "- 수동 확인: Claude Code 세션에서 `/usage` 실행 후 이 절에 붙여넣기(5시간·주간 한도 소진율)."
        )
    lines += [
        "",
        "## 한계",
        "",
        "- 트랜스크립트가 남지 않는 호출(`--no-session-persistence`)·타 프로젝트 디렉터리 세션은 제외.",
        "- 캐시 토큰 단가는 공표 기준의 근사(쓰기 1.25×, 읽기 0.1×). 실제 구독 소비는 별도 산식.",
        "- 창 밖의 준비 작업(계획·코드 작성)은 `--since`를 앞당겨 포함 가능.",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--phase", default="preview")
    ap.add_argument("--since", required=True, help="ISO datetime (tz 포함)")
    ap.add_argument("--until", default=None)
    ap.add_argument(
        "--project-dir",
        default=str(PROJECTS / "-Users-lanoir42-projects-indepth-analysis"),
    )
    ap.add_argument("--session", default=None, help="메인 세션 id (파일 stem)")
    a = ap.parse_args()
    since = datetime.fromisoformat(a.since)
    until = datetime.fromisoformat(a.until) if a.until else datetime.now(UTC)
    res = scan(Path(a.project_dir), since, until, a.session)
    snap = plan_snapshot()
    md = render(res, snap, a.phase, since, until)
    root = Path(a.root)
    (root / "_work").mkdir(parents=True, exist_ok=True)
    dest = root / "_work" / f"usage_report_{a.phase}.md"
    dest.write_text(md, encoding="utf-8")
    agg_json = {f"{k[0]}|{k[1]}": v for k, v in res["agg"].items()}
    (root / "_work" / f"usage_report_{a.phase}.json").write_text(
        json.dumps(
            {
                "since": a.since,
                "until": until.isoformat(),
                "agg": agg_json,
                "plan": {k: v for k, v in snap.items() if k != "data"}
                | ({"data": snap.get("data")} if snap.get("ok") else {}),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
