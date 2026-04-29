"""Claude CLI web search wrapper for Issue Track agents."""

import json
import logging
import subprocess

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT = 150


def issue_web_search(
    prompt: str,
    model: str = _DEFAULT_MODEL,
    timeout: int = _TIMEOUT,
) -> list[dict]:
    """Run a Claude CLI web search and return parsed JSON array."""
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--model",
                model,
                "--output-format",
                "text",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI timed out")
        return []

    if result.returncode != 0:
        logger.warning(
            "Claude CLI failed (exit %d): %s",
            result.returncode,
            result.stderr[:200],
        )
        return []

    return _parse_json_array(result.stdout)


def _parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    if "```" in text:
        lines = text.split("\n")
        json_lines: list[str] = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                json_lines.append(line)
        if json_lines:
            text = "\n".join(json_lines)

    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        logger.warning("No JSON array in Claude output")
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.warning("JSON decode failed")
        return []
