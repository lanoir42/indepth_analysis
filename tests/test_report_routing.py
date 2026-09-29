"""W-a1 라우팅 판정 — 계약 REPORT-ROUTING.md §4 순서·경계값 재현."""
import json
import time

import pytest

from indepth_analysis import report_routing as rr


POLICY = {
    "version": 1,
    "defaults": {"primary": "claude", "budget_policy": "deadline_and_size", "scope": "general"},
    "thresholds": {"gpt_first_below": 70, "claude_first_at": 90},
    "caller": [
        {"caller": "kcif.update_topic", "tier": "haiku", "primary": "auto", "wave": "W-a1"},
        {"caller": "kcif.locked_thing", "tier": "haiku", "primary": "auto", "scope": "nc"},
        {"caller": "kcif.budgeted", "tier": "sonnet", "primary": "auto", "budget_policy": "native_only"},
        {"caller": "kcif.gpt_forced", "tier": "sonnet", "primary": "gpt"},
    ],
}


def _write_policy(tmp_path, data=None):
    p = tmp_path / "report_routing.toml"
    import tomllib
    # round-trip via a tiny manual TOML writer (avoid a tomli_w dependency)
    lines = [f"version = {POLICY['version']}", "[defaults]"]
    for k, v in POLICY["defaults"].items():
        lines.append(f'{k} = "{v}"')
    lines.append("[thresholds]")
    for k, v in POLICY["thresholds"].items():
        lines.append(f"{k} = {v}")
    for c in (data or POLICY)["caller"]:
        lines.append("[[caller]]")
        for k, v in c.items():
            lines.append(f'{k} = "{v}"' if isinstance(v, str) else f"{k} = {v}")
    text = "\n".join(lines) + "\n"
    p.write_text(text, encoding="utf-8")
    # sanity: must actually parse as TOML
    tomllib.loads(text)
    return p


def test_global_claude_is_legacy_regardless_of_policy(tmp_path, monkeypatch):
    monkeypatch.delenv(rr.GLOBAL_ENV, raising=False)
    policy_path = _write_policy(tmp_path)
    route = rr.decide("kcif.update_topic", "haiku", policy=rr.load_policy(policy_path))
    assert route.legacy is True
    assert route.chain == ["claude", "codex"]
    assert route.reason == "global_claude"


def test_missing_policy_file_is_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    monkeypatch.setattr(rr, "load_policy", lambda *a, **k: None)
    route = rr.decide("kcif.update_topic", "haiku")
    assert route.legacy is True
    assert route.reason == "policy_unavailable"


def test_scope_excluded_is_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.locked_thing", "haiku", policy=policy)
    assert route.legacy is True
    assert route.reason == "scope_excluded"


def test_native_only_is_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.budgeted", "sonnet", policy=policy)
    assert route.legacy is True
    assert route.reason == "native_only"


def test_caller_primary_claude_is_legacy_even_in_auto_mode(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.unknown_caller_defaults_to_claude", "haiku", policy=policy)
    assert route.legacy is True
    assert route.reason == "policy_claude"


@pytest.mark.parametrize("used_pct,expected_chain,expected_reason", [
    (10.0, ["codex", "claude"], "usage_low"),
    (69.0, ["codex", "claude"], "usage_low"),
    (70.0, ["codex", "claude"], "usage_mid_haiku"),  # haiku tier -> GPT first even mid-band
    (89.0, ["codex", "claude"], "usage_mid_haiku"),
    (90.0, ["claude"], "usage_high"),
])
def test_auto_thresholds_haiku(monkeypatch, tmp_path, used_pct, expected_chain, expected_reason):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    monkeypatch.setattr(rr, "read_usage_state", lambda *a, **k: {"used_pct": used_pct, "observed_at": time.time()})
    monkeypatch.setattr("indepth_analysis.report_cli.provider_blocked", lambda *_: False)
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.update_topic", "haiku", policy=policy)
    assert route.legacy is False
    assert route.chain == expected_chain
    assert route.reason == expected_reason
    assert route.primary == "auto"


def test_mid_band_non_haiku_prefers_claude(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    monkeypatch.setattr(rr, "read_usage_state", lambda *a, **k: {"used_pct": 80.0, "observed_at": time.time()})
    monkeypatch.setattr("indepth_analysis.report_cli.provider_blocked", lambda *_: False)
    data = dict(POLICY)
    data["caller"] = [{"caller": "kcif.update_topic", "tier": "sonnet", "primary": "auto"}]
    policy = rr.load_policy(_write_policy(tmp_path, data))
    route = rr.decide("kcif.update_topic", "sonnet", policy=policy)
    assert route.chain == ["claude", "codex"]
    assert route.reason == "usage_mid"


def test_unobserved_usage_is_claude_only(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    monkeypatch.setattr(rr, "read_usage_state", lambda *a, **k: None)
    monkeypatch.setattr("indepth_analysis.report_cli.provider_blocked", lambda *_: False)
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.update_topic", "haiku", policy=policy)
    assert route.chain == ["claude"]
    assert route.reason == "usage_unknown"


def test_codex_cooldown_forces_claude_only(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    monkeypatch.setattr(rr, "read_usage_state", lambda *a, **k: {"used_pct": 10.0, "observed_at": time.time()})
    monkeypatch.setattr("indepth_analysis.report_cli.provider_blocked",
                        lambda p: p == "codex")
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.update_topic", "haiku", policy=policy)
    assert route.chain == ["claude"]
    assert route.reason == "codex_cooldown"


def test_claude_cooldown_forces_gpt_only(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    monkeypatch.setattr(rr, "read_usage_state", lambda *a, **k: {"used_pct": 10.0, "observed_at": time.time()})
    monkeypatch.setattr("indepth_analysis.report_cli.provider_blocked",
                        lambda p: p == "claude")
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.update_topic", "haiku", policy=policy)
    assert route.chain == ["codex"]
    assert route.reason == "claude_cooldown"


def test_both_blocked_surfaces_failure(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "auto")
    monkeypatch.setattr(rr, "read_usage_state", lambda *a, **k: {"used_pct": 10.0, "observed_at": time.time()})
    monkeypatch.setattr("indepth_analysis.report_cli.provider_blocked", lambda p: True)
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.update_topic", "haiku", policy=policy)
    assert route.reason == "both_blocked"


def test_global_gpt_mode_forces_auto_callers_to_gpt(monkeypatch, tmp_path):
    monkeypatch.setenv(rr.GLOBAL_ENV, "gpt")
    monkeypatch.setattr("indepth_analysis.report_cli.provider_blocked", lambda *_: False)
    policy = rr.load_policy(_write_policy(tmp_path))
    route = rr.decide("kcif.update_topic", "haiku", policy=policy)
    assert route.chain == ["codex", "claude"]
    assert route.reason == "policy_gpt"


def test_usage_state_stale_and_reset_window_are_unobserved(tmp_path, monkeypatch):
    now = time.time()
    p = tmp_path / "codex_usage.json"
    p.write_text(json.dumps({"used_pct": 5.0, "observed_at": now - 25 * 3600}), encoding="utf-8")
    monkeypatch.setenv(rr.USAGE_ENV, str(p))
    assert rr.read_usage_state(now) is None

    p.write_text(json.dumps({"used_pct": 5.0, "observed_at": now, "resets_at": now - 1}), encoding="utf-8")
    assert rr.read_usage_state(now) is None

    p.write_text(json.dumps({"used_pct": 5.0, "observed_at": now, "resets_at": now + 3600}), encoding="utf-8")
    assert rr.read_usage_state(now) == {"used_pct": 5.0, "observed_at": now, "resets_at": now + 3600}


def test_usage_state_missing_file_is_unobserved(tmp_path, monkeypatch):
    monkeypatch.setenv(rr.USAGE_ENV, str(tmp_path / "does-not-exist.json"))
    assert rr.read_usage_state() is None


def test_malformed_policy_is_none():
    assert rr.parse_policy.__module__ == "indepth_analysis.report_routing"
    with pytest.raises(rr.PolicyError):
        rr.parse_policy({"version": 0})
    with pytest.raises(rr.PolicyError):
        rr.parse_policy({"version": 1, "thresholds": {"gpt_first_below": 95, "claude_first_at": 90}})
