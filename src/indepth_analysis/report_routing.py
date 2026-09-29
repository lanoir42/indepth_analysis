"""리포트 라우팅 — 호출부별 주 공급자 판정 (W-a1, 2026-09-29).

계약 정본: `~/projects/orchestrator/contracts/REPORT-ROUTING.md`. 이 모듈은 그
계약과 같은 의미론(§3~§4)을 이 저장소 안에서 구현하되 orchestrator 코드를
import하지 않는다 — 형제 저장소는 파일 계약(정책 TOML·사용률 상태 파일)만
공유한다.

이 저장소가 실제로 정책에 올리는 caller는 W-a1 범위 하나뿐이다:
`kcif.update_topic`(계약 §7-1 caller 목록과 글자 그대로 같아야 parity report가
집계한다).

**기본값은 동작 변화 0이다.** 전역 `INDEPTH_REPORT_PRIMARY`가 없거나 `claude`면
`decide()`는 `legacy=True`를 돌려주고 `report_cli.complete()`는 caller를 몰랐을
때와 순서가 같은 체인(`[claude, codex]`)으로 시도한다. 정책 파일의 caller 항목이
`primary = "auto"`여도 전역 스위치를 `auto`/`gpt`로 올리기 전까지는 잠들어 있다.

사용률 상태 파일(`~/.config/report-routing/codex_usage.json`)은 orchestrator
`briefing routing observe`만 쓴다 — 이 저장소는 **읽기만** 한다(계약 §1).
"""
from __future__ import annotations

import json
import os
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "report_routing.toml"
GLOBAL_ENV = "INDEPTH_REPORT_PRIMARY"
USAGE_ENV = "REPORT_ROUTING_USAGE_PATH"
DEFAULT_USAGE_PATH = Path.home() / ".config" / "report-routing" / "codex_usage.json"
MODES = ("claude", "gpt", "auto")
EXCLUDED_SCOPES = frozenset({"nc", "gb"})
_DEFAULT_THRESHOLDS = {"gpt_first_below": 70.0, "claude_first_at": 90.0, "stale_after_hours": 24.0}


@dataclass(frozen=True)
class CallerPolicy:
    caller: str
    tier: str = "sonnet"
    primary: str = "claude"
    budget_policy: str = "deadline_and_size"
    scope: str = "general"
    wave: str = ""


@dataclass(frozen=True)
class Policy:
    version: int
    defaults: CallerPolicy
    thresholds: dict
    callers: dict

    def entry(self, caller: str) -> CallerPolicy:
        return self.callers.get(caller) or CallerPolicy(
            caller=caller, tier=self.defaults.tier, primary=self.defaults.primary,
            budget_policy=self.defaults.budget_policy, scope=self.defaults.scope)


@dataclass
class Route:
    chain: list
    reason: str
    mode: str                 # 전역 모드(claude/gpt/auto)
    legacy: bool              # True면 report_cli.complete()가 종전 경로를 그대로 탄다
    policy_version: int = 0
    primary: str = "claude"   # 호출부 실효 primary(claude/gpt/auto)
    usage_pct: float | None = None
    usage_observed_at: float | None = None


class PolicyError(ValueError):
    pass


def parse_policy(data: dict) -> Policy:
    """TOML dict → Policy. 잘못된 값은 PolicyError(조용히 기본값으로 강등하지 않는다)."""
    version = int(data.get("version") or 0)
    if version < 1:
        raise PolicyError("version")
    d = data.get("defaults") or {}
    defaults = CallerPolicy(caller="*", tier=d.get("tier", "sonnet"),
                            primary=d.get("primary", "claude"),
                            budget_policy=d.get("budget_policy", "deadline_and_size"),
                            scope=d.get("scope", "general"))
    th = dict(_DEFAULT_THRESHOLDS)
    for k, v in (data.get("thresholds") or {}).items():
        if k == "refresh_after_minutes":
            continue  # 관측기를 가진 저장소(orchestrator)만 의미 있음
        if k not in th:
            raise PolicyError(f"threshold:{k}")
        th[k] = float(v)
    if not 0 <= th["gpt_first_below"] <= th["claude_first_at"] <= 100:
        raise PolicyError("threshold_order")
    callers = {}
    for row in data.get("caller") or []:
        name = row.get("caller")
        if not name or name in callers:
            raise PolicyError(f"caller:{name}")
        cp = CallerPolicy(caller=name, tier=row.get("tier", defaults.tier),
                          primary=row.get("primary", defaults.primary),
                          budget_policy=row.get("budget_policy", defaults.budget_policy),
                          scope=row.get("scope", defaults.scope), wave=row.get("wave", ""))
        if cp.primary not in MODES or cp.budget_policy not in ("native_only", "deadline_and_size") \
                or cp.tier not in ("opus", "sonnet", "haiku"):
            raise PolicyError(f"caller:{name}")
        callers[name] = cp
    if defaults.primary not in MODES:
        raise PolicyError("defaults")
    return Policy(version, defaults, th, callers)


_cache: dict = {}


def load_policy(path: Path | None = None) -> Policy | None:
    """정책 파일 로드(mtime 캐시). 없거나 깨지면 None — 호출부는 종전 경로로 간다."""
    p = Path(path) if path else POLICY_PATH
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        if _cache.get("key") == key:
            return _cache["policy"]
        with open(p, "rb") as fh:
            policy = parse_policy(tomllib.load(fh))
    except (OSError, tomllib.TOMLDecodeError, PolicyError, ValueError, TypeError):
        return None
    _cache.update(key=key, policy=policy)
    return policy


def global_mode() -> str:
    raw = (os.environ.get(GLOBAL_ENV) or "claude").strip().lower()
    return raw if raw in MODES else "claude"


def usage_path() -> Path:
    override = os.environ.get(USAGE_ENV)
    return Path(override) if override else DEFAULT_USAGE_PATH


def read_usage_state(now: float | None = None, stale_after_hours: float = 24.0) -> dict | None:
    """사용률 상태 파일을 읽기만 한다(쓰지 않는다 — 계약 §1). 미관측은 None."""
    now = now if now is not None else time.time()
    try:
        data = json.loads(usage_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    used, observed = data.get("used_pct"), data.get("observed_at")
    if not isinstance(used, (int, float)) or isinstance(used, bool):
        return None
    if not isinstance(observed, (int, float)) or isinstance(observed, bool):
        return None
    if now - float(observed) > stale_after_hours * 3600:
        return None
    resets_at = data.get("resets_at")
    if isinstance(resets_at, (int, float)) and not isinstance(resets_at, bool) and resets_at <= now:
        return None  # 창이 넘어갔다 — 새 창의 값은 아직 모른다(추정 금지)
    return data


def _legacy(reason, mode, policy, primary="claude") -> Route:
    version = policy.version if policy else 0
    return Route(["claude", "codex"], reason, mode, True, version, primary)


def decide(caller: str, tier: str = "sonnet", *, policy: Policy | None = None,
           now: float | None = None) -> Route:
    """caller·등급 → 공급자 체인과 사유(계약 §4)."""
    mode = global_mode()
    if mode == "claude":
        return _legacy("global_claude", mode, policy)
    policy = policy or load_policy()
    if policy is None:
        return _legacy("policy_unavailable", mode, None)
    entry = policy.entry(caller)
    if entry.scope in EXCLUDED_SCOPES:
        return _legacy("scope_excluded", mode, policy)
    if entry.budget_policy == "native_only":
        return _legacy("native_only", mode, policy)
    primary = entry.primary
    if mode == "gpt" and primary == "auto":
        primary = "gpt"
    if primary == "claude":
        return _legacy("policy_claude", mode, policy)

    from indepth_analysis.report_cli import provider_blocked  # 지연 임포트 — 순환 회피
    codex_blocked = provider_blocked("codex")
    claude_blocked = provider_blocked("claude")
    stale = policy.thresholds["stale_after_hours"]
    st = read_usage_state(now, stale) if primary == "auto" else None
    u = float(st["used_pct"]) if st else None

    if primary == "gpt":
        if codex_blocked:
            chain, reason = ["claude"], "codex_cooldown"
        else:
            chain, reason = ["codex", "claude"], "policy_gpt"
    elif codex_blocked:
        chain, reason = ["claude"], "codex_cooldown"
    elif u is None:
        chain, reason = ["claude"], "usage_unknown"
    elif u >= policy.thresholds["claude_first_at"]:
        chain, reason = ["claude"], "usage_high"
    elif u >= policy.thresholds["gpt_first_below"]:
        if tier == "haiku":
            chain, reason = ["codex", "claude"], "usage_mid_haiku"
        else:
            chain, reason = ["claude", "codex"], "usage_mid"
    else:
        chain, reason = ["codex", "claude"], "usage_low"

    if claude_blocked:
        if codex_blocked:
            chain, reason = ["claude", "codex"], "both_blocked"  # 실패를 표면화한다
        else:
            chain, reason = ["codex"], "claude_cooldown"

    return Route(chain, reason, mode, False, policy.version, primary, u,
                st.get("observed_at") if st else None)
