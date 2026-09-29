"""W-a1/W-b 섀도 캡처 드롭 — `kcif.update_topic`·`kcif.monthly` (계약
REPORT-ROUTING.md §7).

정본 계약: `~/projects/orchestrator/contracts/REPORT-ROUTING.md` §7-1(캡처
드롭)·§7-3(캡처 JSON 형식). `kcif.update_topic`(W-a1, haiku)과 `kcif.monthly`
(W-b, sonnet — `kcif/report.py:_render_period`의 월간 종합 서술 콜, 도구 없음)는
평문 프롬프트 1개로 재현 가능한 호출(도구·스키마 파일 없음)이라 **캡처 드롭**
대상이다 — 이 저장소가 하는 일은 실제 호출에 보낸 정확한 프롬프트를 JSON으로
남기는 것뿐이고, LLM 추가 호출은 0회다. orchestrator의 밤 틱(`parity nightly`)이
그 캡처를 양쪽 공급자로 재현해 쌍을 만들고 판정한다.

`monthly_brief research`(웹 검색 도구 사용, 1800초·동시 8)는 이 캐처 대상이
**아니다** — 그 호출은 WebSearch/WebFetch를 쓰고 GPT 쪽이 동일 도구를 못 가질
수 있어 재현 불가(설계 §5-1 W-b 비고). `kcif.monthly`는 그 결과물 위에서 돌아가는
별개의, 도구 없는 서술 전용 콜이라 재현 가능하다.

기본 켜짐(`INDEPTH_PARITY_SHADOW`, `0`으로 끌 수 있음). 쓰기 실패는 삼킨다 —
리포트 생성(워터마크 전진)을 절대 막지 않는다(계약 §7-2).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

#: 드롭 루트 — orchestrator `journal/parity/`(계약 §7). 환경변수로 재정의 가능
#: (테스트·격리 실행용). journal/은 gitignore·서버 화이트리스트 밖이라 앱·저널에
#: 안 보인다.
DIR_ENV = "BRIEFING_PARITY_DIR"
DEFAULT_DIR = Path.home() / "projects" / "orchestrator" / "journal" / "parity"
SHADOW_ENV = "INDEPTH_PARITY_SHADOW"
DAILY_CAP = 3
MAX_PROMPT_CHARS = 400_000


def enabled() -> bool:
    return os.environ.get(SHADOW_ENV, "1") == "1"


def _root() -> Path:
    override = os.environ.get(DIR_ENV)
    return Path(override) if override else DEFAULT_DIR


def _safe_caller(caller: str) -> str:
    return re.sub(r"[/\s]+", "_", caller)


def input_hash(prompt: str, system_prompt: str | None = None, json_schema=None) -> str:
    """계약 §7-3 `input_sha1` — 참조 구현은 `briefing/parity/store.input_hash`."""
    if system_prompt is None and json_schema is None:
        return hashlib.sha1(prompt.encode("utf-8")).hexdigest()
    s = system_prompt or ""
    j = json.dumps(json_schema, ensure_ascii=False, sort_keys=True) if json_schema is not None else ""
    return hashlib.sha1((s + "\n\x00\n" + prompt + "\n\x00\n" + j).encode("utf-8")).hexdigest()


def _today_state(caller_dir: Path, today: str, sha8: str) -> tuple[int, bool]:
    """(오늘 캡처 수, 같은 입력 중복 여부). 디렉토리가 없으면 (0, False)."""
    if not caller_dir.is_dir():
        return 0, False
    count = 0
    dup = False
    for p in caller_dir.glob("*.json"):
        name = p.name
        if sha8 in name:
            dup = True
        if name.startswith(today + "-"):
            count += 1
    return count, dup


def maybe_write(*, caller: str, repo: str, tier: str, prompt: str, scope: str = "general",
                system_prompt: str | None = None, json_schema=None,
                meta: dict | None = None) -> Path | None:
    """조건 충족 시 캡처 JSON 1건을 원자 쓰기. 실패·상한·중복은 조용히 None."""
    if not enabled() or not prompt or len(prompt) > MAX_PROMPT_CHARS:
        return None
    try:
        sha1 = input_hash(prompt, system_prompt, json_schema)
        sha8 = sha1[:8]
        caller_dir = _root() / "_captures" / _safe_caller(caller)
        now = datetime.now()
        today = now.strftime("%Y%m%d")
        count, dup = _today_state(caller_dir, today, sha8)
        if dup or count >= DAILY_CAP:
            return None
        caller_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(caller_dir, 0o700)
            os.chmod(caller_dir.parent, 0o700)
        except OSError:
            pass
        payload = {
            "v": 2, "caller": caller, "repo": repo, "tier": tier,
            "captured_at": now.isoformat(timespec="seconds"),
            "prompt": prompt, "system_prompt": system_prompt, "json_schema": json_schema,
            "input_sha1": sha1, "scope": scope, "meta": meta or {},
        }
        name = f"{now.strftime('%Y%m%d-%H%M%S')}_{sha8}.json"
        tmp = caller_dir / f".{name}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        final = caller_dir / name
        tmp.rename(final)
        return final
    except Exception:  # noqa: BLE001 — 섀도 실패는 절대 리포트 생성을 막지 않는다(계약 §7-2)
        return None
