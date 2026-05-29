"""Weekly brief orchestrator — 3 parallel agents → synthesis → evaluator → R2."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bgilib.obs import CallKind, span
from bgilib.obs.extractors.claude_cli import parse_stream_json_text

from indepth_analysis.skills.euro_macro.weekly_brief.prompts import (
    ECB_MARKET_AGENT_PROMPT,
    EVALUATOR_SYSTEM_PROMPT,
    GENERATOR_R2_SYSTEM_PROMPT,
    GENERATOR_R2_USER_PROMPT,
    HICP_AGENT_PROMPT,
    PMI_GDP_AGENT_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_PROMPT,
)

logger = logging.getLogger(__name__)


@dataclass
class WeeklyBriefResult:
    """Output of a full weekly_brief pipeline run."""

    date_str: str
    slide_text: str
    slide_json: str
    combined_path: Path
    high_issues: str = ""
    medium_issues: str = ""
    model_used: str = ""
    generated_at: str = ""
    extra_paths: dict[str, Path] = field(default_factory=dict)


class WeeklyBriefOrchestrator:
    """Run 3 collection agents in parallel, synthesize, evaluate, revise, save."""

    MODEL = "claude-opus-4-20250514"
    AGENT_TIMEOUT = 300  # default seconds per Claude CLI agent (WebSearch is slow)
    # Per-agent overrides: hicp and pmi_gdp each source 28 months of multi-series
    # time-series data via WebSearch, which runs near the time limit; give them
    # more room than ecb_market (current-snapshot data that completes quickly).
    AGENT_TIMEOUTS = {"hicp": 420, "pmi_gdp": 420}
    SYNTHESIS_TIMEOUT = 300
    EVALUATOR_TIMEOUT = 120
    R2_TIMEOUT = 240

    def __init__(
        self,
        model: str = MODEL,
        no_evaluator: bool = False,
    ) -> None:
        self.model = model
        self.no_evaluator = no_evaluator

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, date_str: str) -> WeeklyBriefResult:
        """Full pipeline: collect → synthesize → evaluate → (revise) → save."""
        logger.info("WeeklyBrief: start (date=%s, model=%s)", date_str, self.model)

        hicp, pmi_gdp, ecb_market = asyncio.run(self._collect_all())
        logger.info(
            "WeeklyBrief: agents done (hicp=%d, pmi_gdp=%d, ecb_market=%d chars)",
            len(hicp),
            len(pmi_gdp),
            len(ecb_market),
        )

        synthesis_raw = self._synthesize(date_str, hicp, pmi_gdp, ecb_market)
        slide_text, slide_json = self._extract_blocks(synthesis_raw)
        logger.info(
            "WeeklyBrief: synthesis ok (text=%d chars, json=%d chars)",
            len(slide_text),
            len(slide_json),
        )

        high_issues = ""
        medium_issues = ""
        if not self.no_evaluator:
            try:
                evaluator_raw = self._evaluate(slide_text, slide_json)
                high_issues, medium_issues = self._extract_issues(evaluator_raw)
                logger.info(
                    "WeeklyBrief: evaluator HIGH=%s MEDIUM=%s",
                    "yes" if high_issues.strip() else "no",
                    "yes" if medium_issues.strip() else "no",
                )
            except Exception as exc:
                logger.warning("WeeklyBrief evaluator failed (non-fatal): %s", exc)

            if high_issues and high_issues.strip() and high_issues.strip() != "(없음)":
                try:
                    r2_raw = self._generate_r2(slide_text, slide_json, high_issues)
                    new_text, new_json = self._extract_blocks(r2_raw)
                    if new_text and new_json:
                        slide_text, slide_json = new_text, new_json
                        logger.info("WeeklyBrief: R2 applied")
                except Exception as exc:
                    logger.warning("WeeklyBrief R2 failed (non-fatal): %s", exc)

        result = self.save(slide_text, slide_json, date_str)
        result.high_issues = high_issues
        result.medium_issues = medium_issues
        result.model_used = self.model
        result.generated_at = datetime.now(UTC).isoformat()
        return result

    # ------------------------------------------------------------------
    # Async parallel collection
    # ------------------------------------------------------------------

    async def _collect_all(self) -> tuple[str, str, str]:
        """Run 3 Claude CLI agents in parallel; gracefully default to '' on failure."""
        tasks = [
            self._run_agent(HICP_AGENT_PROMPT, "hicp"),
            self._run_agent(PMI_GDP_AGENT_PROMPT, "pmi_gdp"),
            self._run_agent(ECB_MARKET_AGENT_PROMPT, "ecb_market"),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: list[str] = []
        for name, r in zip(("hicp", "pmi_gdp", "ecb_market"), results):
            if isinstance(r, BaseException):
                logger.warning("WeeklyBrief agent %s failed: %s", name, r)
                out.append("")
            else:
                out.append(r)
        return out[0], out[1], out[2]

    async def _run_agent(self, prompt: str, name: str) -> str:
        """Run a single Claude CLI agent (async). Returns parsed text or ''."""
        timeout = self.AGENT_TIMEOUTS.get(name, self.AGENT_TIMEOUT)
        cmd = [
            "claude",
            "-p", prompt,
            "--allowedTools", "WebSearch WebFetch",
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.model,
        ]

        logger.info("WeeklyBrief agent %s: starting", name)
        async with span(
            project="indepth_analysis",
            provider="anthropic",
            model=self.model,
            call_kind=CallKind.CLI_SUBPROCESS,
            function_name="WeeklyBriefOrchestrator._run_agent",
            tags={"agent": name},
        ) as obs_handle:
            obs_handle.set_text_len(len(prompt))
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                obs_handle.set_error("claude CLI not found")
                raise RuntimeError(
                    "claude CLI not found in PATH — is it installed?"
                ) from exc

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                obs_handle.set_error("timeout")
                raise RuntimeError(
                    f"WeeklyBrief agent {name!r} timed out after {timeout}s"
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                logger.warning(
                    "WeeklyBrief agent %s exited %d: %s",
                    name,
                    proc.returncode,
                    stderr[:300],
                )
                obs_handle.set_error(f"exit {proc.returncode}")
                raise RuntimeError(
                    f"Claude CLI exited {proc.returncode} for agent {name!r}"
                )

            try:
                cli_result = parse_stream_json_text(stdout)
                obs_handle.set_usage(cli_result.usage)
            except Exception:
                logger.debug("usage extraction failed for WeeklyBrief agent %s", name)

        text = self._parse_stream_json(stdout)
        if not text:
            logger.warning("WeeklyBrief agent %s: empty output", name)
        return text

    # ------------------------------------------------------------------
    # Synchronous Claude CLI calls (synthesis / evaluator / R2)
    # ------------------------------------------------------------------

    def _synthesize(
        self,
        date_str: str,
        hicp: str,
        pmi_gdp: str,
        ecb_market: str,
    ) -> str:
        user_prompt = SYNTHESIS_USER_PROMPT.format(
            date_str=date_str,
            hicp_data=hicp or "(데이터 없음)",
            pmi_gdp_data=pmi_gdp or "(데이터 없음)",
            ecb_market_data=ecb_market or "(데이터 없음)",
        )
        return self._call_claude(
            user_prompt=user_prompt,
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            timeout=self.SYNTHESIS_TIMEOUT,
            label="synthesis",
        )

    def _evaluate(self, slide_text: str, slide_json: str) -> str:
        user_prompt = (
            "## 슬라이드 텍스트\n"
            f"{slide_text}\n\n"
            "## 차트 JSON\n"
            f"```json\n{slide_json}\n```\n\n"
            "위 슬라이드를 평가하고 HIGH/MEDIUM 이슈를 출력하세요."
        )
        return self._call_claude(
            user_prompt=user_prompt,
            system_prompt=EVALUATOR_SYSTEM_PROMPT,
            timeout=self.EVALUATOR_TIMEOUT,
            label="evaluator",
        )

    def _generate_r2(
        self, slide_text: str, slide_json: str, high_issues: str
    ) -> str:
        user_prompt = GENERATOR_R2_USER_PROMPT.format(
            slide_text=slide_text,
            slide_json=slide_json,
            high_issues=high_issues,
        )
        return self._call_claude(
            user_prompt=user_prompt,
            system_prompt=GENERATOR_R2_SYSTEM_PROMPT,
            timeout=self.R2_TIMEOUT,
            label="generator_r2",
        )

    def _call_claude(
        self,
        user_prompt: str,
        system_prompt: str,
        timeout: int,
        label: str,
    ) -> str:
        """Synchronous Claude CLI call — no extra tools, pure text generation."""
        cmd = [
            "claude",
            "-p", user_prompt,
            "--append-system-prompt", system_prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.model,
        ]
        logger.info("WeeklyBrief %s: calling Claude CLI", label)
        with span(
            project="indepth_analysis",
            provider="anthropic",
            model=self.model,
            call_kind=CallKind.CLI_SUBPROCESS,
            function_name="WeeklyBriefOrchestrator._call_claude",
            tags={"label": label},
        ) as obs_handle:
            obs_handle.set_text_len(len(user_prompt), system_len=len(system_prompt))
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(Path("/tmp")),
                )
            except FileNotFoundError as exc:
                obs_handle.set_error("claude CLI not found")
                raise RuntimeError(
                    "claude CLI not found in PATH — is it installed?"
                ) from exc

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                obs_handle.set_error("timeout")
                raise RuntimeError(
                    f"Claude CLI ({label}) timed out after {timeout}s"
                )

            if proc.returncode != 0:
                obs_handle.set_error(f"exit {proc.returncode}")
                raise RuntimeError(
                    f"Claude CLI ({label}) failed (exit {proc.returncode}): "
                    f"{(stderr or '')[:500]}"
                )

            try:
                cli_result = parse_stream_json_text(stdout)
                obs_handle.set_usage(cli_result.usage)
            except Exception:
                logger.debug("usage extraction failed for WeeklyBrief %s", label)

        return self._parse_stream_json(stdout)

    # ------------------------------------------------------------------
    # Stream-json parsing + block extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_stream_json(raw: bytes | str) -> str:
        """Collect assistant text from stream-json output, fallback to result."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        text_parts: list[str] = []
        result_text = ""
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = obj.get("type", "")
            if t == "assistant":
                for block in obj.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
            elif t == "result" and obj.get("subtype") == "success":
                r = (obj.get("result") or "").strip()
                if r:
                    result_text = r
        return result_text or "".join(text_parts)

    @staticmethod
    def _extract_between(text: str, start: str, end: str) -> str:
        pattern = re.compile(
            re.escape(start) + r"\s*(.*?)\s*" + re.escape(end),
            re.DOTALL,
        )
        m = pattern.search(text)
        return m.group(1).strip() if m else ""

    def _extract_blocks(self, text: str) -> tuple[str, str]:
        """Extract SLIDE_TEXT and SLIDE_JSON blocks. Best-effort fallback."""
        slide_text = self._extract_between(
            text, "===SLIDE_TEXT_START===", "===SLIDE_TEXT_END==="
        )
        slide_json = self._extract_between(
            text, "===SLIDE_JSON_START===", "===SLIDE_JSON_END==="
        )

        if slide_json:
            # Strip markdown fence if model wrapped JSON in ```json ... ```
            fence_match = re.match(
                r"```(?:json)?\s*(.*?)\s*```",
                slide_json,
                re.DOTALL,
            )
            if fence_match:
                slide_json = fence_match.group(1).strip()

        if not slide_text:
            slide_text = text.strip()
        return slide_text, slide_json

    def _extract_issues(self, text: str) -> tuple[str, str]:
        """Extract HIGH and MEDIUM issue blocks from evaluator output."""
        high = self._extract_between(text, "===HIGH_START===", "===HIGH_END===")
        medium = self._extract_between(text, "===MEDIUM_START===", "===MEDIUM_END===")
        return high, medium

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(
        self,
        slide_text: str,
        slide_json: str,
        date_str: str,
    ) -> WeeklyBriefResult:
        """Write slide_text_r2.md, slide_data_r2.json, and combined markdown."""
        out_dir = Path("reports") / f"euro_macro_brief_{date_str}"
        out_dir.mkdir(parents=True, exist_ok=True)

        text_path = out_dir / "slide_text_r2.md"
        json_path = out_dir / "slide_data_r2.json"
        combined_path = out_dir / f"euro_macro_brief_slide_{date_str}.md"

        text_path.write_text(slide_text + "\n", encoding="utf-8")

        # Pretty-print JSON if parseable, otherwise write raw.
        json_to_write = slide_json
        try:
            parsed = json.loads(slide_json)
            json_to_write = json.dumps(parsed, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, ValueError):
            logger.warning("slide_json is not valid JSON — writing raw text")

        json_path.write_text(json_to_write + "\n", encoding="utf-8")

        combined = (
            f"# Macroeconomic Brief: 유럽 — {date_str}\n\n"
            f"{slide_text.strip()}\n\n"
            "## Chart Data (JSON)\n\n"
            "```json\n"
            f"{json_to_write.strip()}\n"
            "```\n"
        )
        combined_path.write_text(combined, encoding="utf-8")

        return WeeklyBriefResult(
            date_str=date_str,
            slide_text=slide_text,
            slide_json=json_to_write,
            combined_path=combined_path,
            extra_paths={"slide_text": text_path, "slide_json": json_path},
        )
