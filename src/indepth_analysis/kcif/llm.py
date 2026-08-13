"""bgilib ClaudeClient 래퍼 — JSON 강제·검증을 직접 담당.

bgilib에는 telegram router의 json_schema 같은 스키마 강제가 없다
(``json_mode=True``는 CLI ``--output-format json`` 래퍼 파싱일 뿐).
여기서 JSON-only 지시 + 코드펜스 스트립 + json.loads + 필드 검증까지 한다.
실패는 None 반환 — 호출부가 워터마크를 전진시키지 않아 다음 실행이 재시도.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_JSON_ONLY = "\n\n반드시 유효한 JSON 객체 하나로만 응답하세요. 코드펜스·설명·머리말 금지."


def _strip_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    # 앞뒤 잡담 방어: 첫 '{'부터 마지막 '}'까지
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        t = t[i:j + 1]
    return t


def call_json(prompt: str, *, system: str, model: str = "haiku",
              timeout: int = 180, required_keys: tuple[str, ...] = ()) -> dict | None:
    """JSON 응답 1회 + 파싱 실패 시 1회 재시도. 최종 실패는 None."""
    from bgilib.llm.claude import ClaudeClient, LLMError, LLMTimeoutError

    client = ClaudeClient(model=model, timeout=timeout)
    sys_prompt = system + _JSON_ONLY
    for attempt in (1, 2):
        try:
            result = client.complete(prompt, system=sys_prompt)
            data = json.loads(_strip_fences(result.text))
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
            missing = [k for k in required_keys if k not in data]
            if missing:
                raise ValueError(f"missing keys: {missing}")
            return data
        except (LLMError, LLMTimeoutError) as e:
            logger.warning("kcif llm call failed (attempt %d): %s", attempt, e)
        except (ValueError, TypeError) as e:
            logger.warning("kcif llm bad JSON (attempt %d): %s", attempt, e)
    return None


def call_text(prompt: str, *, system: str, model: str = "sonnet",
              timeout: int = 300) -> str | None:
    """자유 텍스트 1회 (월간/분기 종합 서술용). 실패는 None."""
    from bgilib.llm.claude import ClaudeClient, LLMError, LLMTimeoutError

    try:
        client = ClaudeClient(model=model, timeout=timeout)
        return client.complete(prompt, system=system).text.strip()
    except (LLMError, LLMTimeoutError) as e:
        logger.warning("kcif llm text call failed: %s", e)
        return None
