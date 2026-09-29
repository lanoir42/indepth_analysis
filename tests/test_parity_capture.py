"""W-a1 섀도 캡처 드롭 — 계약 REPORT-ROUTING.md §7-1/§7-3 재현.

모든 테스트는 ``BRIEFING_PARITY_DIR``을 tmp_path로 돌려 실제
``~/projects/orchestrator/journal/parity/``에 쓰지 않는다.
"""
import json

from indepth_analysis import parity_capture as pc


def test_disabled_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(pc.DIR_ENV, str(tmp_path))
    monkeypatch.setenv(pc.SHADOW_ENV, "0")
    out = pc.maybe_write(caller="kcif.update_topic", repo="indepth_analysis", tier="haiku",
                         prompt="hello world")
    assert out is None
    assert not any(tmp_path.rglob("*.json"))


def test_writes_capture_json_with_contract_fields(tmp_path, monkeypatch):
    monkeypatch.setenv(pc.DIR_ENV, str(tmp_path))
    monkeypatch.delenv(pc.SHADOW_ENV, raising=False)  # default ON
    out = pc.maybe_write(caller="kcif.update_topic", repo="indepth_analysis", tier="haiku",
                         prompt="토픽 프롬프트 본문")
    assert out is not None
    assert out.parent.name == "kcif.update_topic"
    assert out.parent.parent.name == "_captures"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["v"] == 2
    assert data["caller"] == "kcif.update_topic"
    assert data["repo"] == "indepth_analysis"
    assert data["tier"] == "haiku"
    assert data["prompt"] == "토픽 프롬프트 본문"
    assert data["scope"] == "general"
    assert data["input_sha1"] == pc.input_hash("토픽 프롬프트 본문")
    assert out.stat().st_mode & 0o777 == 0o600


def test_caller_with_slash_and_space_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.setenv(pc.DIR_ENV, str(tmp_path))
    out = pc.maybe_write(caller="weird/caller name", repo="indepth_analysis", tier="haiku",
                         prompt="x")
    assert out.parent.name == "weird_caller_name"


def test_daily_cap_is_three(tmp_path, monkeypatch):
    monkeypatch.setenv(pc.DIR_ENV, str(tmp_path))
    for i in range(3):
        out = pc.maybe_write(caller="kcif.update_topic", repo="indepth_analysis", tier="haiku",
                             prompt=f"prompt {i}")
        assert out is not None
    fourth = pc.maybe_write(caller="kcif.update_topic", repo="indepth_analysis", tier="haiku",
                            prompt="prompt 3")
    assert fourth is None


def test_duplicate_input_hash_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv(pc.DIR_ENV, str(tmp_path))
    first = pc.maybe_write(caller="kcif.update_topic", repo="indepth_analysis", tier="haiku",
                           prompt="same prompt")
    assert first is not None
    dup = pc.maybe_write(caller="kcif.update_topic", repo="indepth_analysis", tier="haiku",
                         prompt="same prompt")
    assert dup is None


def test_oversized_prompt_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv(pc.DIR_ENV, str(tmp_path))
    huge = "x" * (pc.MAX_PROMPT_CHARS + 1)
    assert pc.maybe_write(caller="kcif.update_topic", repo="indepth_analysis", tier="haiku",
                          prompt=huge) is None


def test_write_failure_is_swallowed(tmp_path, monkeypatch):
    # Point the root at a path that can never become a directory (a file in its place).
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv(pc.DIR_ENV, str(blocker))
    assert pc.maybe_write(caller="kcif.update_topic", repo="indepth_analysis", tier="haiku",
                          prompt="x") is None
