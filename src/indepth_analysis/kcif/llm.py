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
              timeout: int = 180, required_keys: tuple[str, ...] = (),
              caller: str | None = None) -> dict | None:
    """JSON 응답 1회 + 파싱 실패 시 1회 재시도. 최종 실패는 None.

    ``caller``는 W-a1 라우팅 훅(opt-in) — 지금은 ``kcif.update_topic``만 넘긴다.
    나머지 호출부(``expand_keywords``·``resummarize_topic``)는 그대로 ``None``이라
    동작이 한 글자도 바뀌지 않는다.
    """
    from indepth_analysis.report_cli import enabled, complete, ReportCLIError
    if enabled():
        def validate(text):
            value = json.loads(_strip_fences(text))
            if not isinstance(value, dict) or any(key not in value for key in required_keys):
                raise ValueError("JSON contract")
        try:
            text = complete(system + _JSON_ONLY + "\n\n" + prompt, tier=model,
                            timeout=timeout, validate=validate, caller=caller)
            return json.loads(_strip_fences(text))
        except ReportCLIError:
            logger.warning("kcif report providers unavailable; watermark must stay unchanged")
            return None

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
              timeout: int = 300, caller: str | None = None) -> str | None:
    """자유 텍스트 1회 (월간/분기 종합 서술용). 실패는 None.

    ``caller``는 W-a1과 같은 opt-in 라우팅/섀도 훅 — 지금은 ``kcif.monthly``만
    넘긴다(``kcif/report.py``의 월간 호출 1곳). 분기 호출은 그대로 ``None``이라
    동작이 한 글자도 바뀌지 않는다.
    """
    from indepth_analysis.report_cli import enabled, complete, ReportCLIError
    if enabled():
        try:
            return complete(system + "\n\n" + prompt, tier=model, timeout=timeout,
                            caller=caller)
        except ReportCLIError:
            logger.warning("kcif report providers unavailable")
            return None

    from bgilib.llm.claude import ClaudeClient, LLMError, LLMTimeoutError

    try:
        client = ClaudeClient(model=model, timeout=timeout)
        return client.complete(prompt, system=system).text.strip()
    except (LLMError, LLMTimeoutError) as e:
        logger.warning("kcif llm text call failed: %s", e)
        return None
