"""Orchestrator — runs agents in parallel, deduplicates, persists, synthesizes."""

import asyncio
import json
import logging
import re
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from indepth_analysis.models.issue_track import (
    CredibilityRating,
    CredibilityRubric,
    Evidence,
    IssueReport,
    IssueRun,
)
from indepth_analysis.skills.issue_track.agents import (
    PrimarySourceAgent,
    SocialBlogAgent,
    TelegramRecallAgent,
    Tier1MediaAgent,
)
from indepth_analysis.skills.issue_track.agents.base import IssueRunContext
from indepth_analysis.skills.issue_track.agents.claude_search import issue_web_search
from indepth_analysis.skills.issue_track.prompts import (
    KEYWORDS_EXTRACT_PROMPT,
    SLUG_EXTRACT_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_PROMPT,
)
from indepth_analysis.skills.issue_track.renderer import render_report, update_index
from indepth_analysis.skills.issue_track.store import IssueStore

logger = logging.getLogger(__name__)

_ALLOWED_MODELS = frozenset(
    {
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "claude-sonnet-4-6-20260401",
        "claude-opus-4-6-20260401",
    }
)


def _make_run_id() -> str:
    now = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{now}-{uuid.uuid4().hex[:6]}"


def _extract_slug(topic: str) -> str:
    """Use Claude to extract a slug from the topic."""
    prompt = SLUG_EXTRACT_PROMPT.format(topic=topic)
    items = issue_web_search(prompt, model="claude-haiku-4-5-20251001", timeout=30)
    # issue_web_search returns JSON array, but slug prompt returns plain text
    # Fall back to simple slug generation
    raw = ""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "claude-haiku-4-5-20251001", "--output-format", "text"],
            capture_output=True, text=True, timeout=30,
        )
        raw = result.stdout.strip().lower()
    except Exception:
        pass

    if raw and re.match(r"^[a-z0-9-]+$", raw):
        return raw[:60]

    # Fallback: simple slug from first words
    words = re.sub(r"[^a-z0-9\s]", "", topic.lower()).split()[:5]
    return "-".join(words)[:60] or "issue"


def _extract_keywords(topic: str) -> list[str]:
    """Use Claude Haiku to extract search keywords."""
    prompt = KEYWORDS_EXTRACT_PROMPT.format(topic=topic)
    items = issue_web_search(prompt, model="claude-haiku-4-5-20251001", timeout=30)
    if items and all(isinstance(k, str) for k in items):
        return [str(k) for k in items[:8]]
    return [topic]


def _build_evidence_context(all_evidence: list[Evidence]) -> str:
    """Build context string for synthesis prompt."""
    parts: list[str] = []
    for ev in all_evidence:
        tier_label = {1: "1차자료", 2: "주요매체", 3: "소셜/블로그", 4: "Telegram"}.get(ev.tier, f"tier{ev.tier}")
        cred_str = f" [신뢰도: {ev.credibility_score:.1f}/5]" if ev.credibility_score is not None and ev.tier == 3 else ""
        source = ev.source_name or ev.source_handle or ""
        date_str = f" ({ev.published_at})" if ev.published_at else ""
        title = ev.title or "(제목없음)"
        parts.append(
            f"[{tier_label}][{ev.stance}]{cred_str} **{title}**"
            f" — {source}{date_str}\n"
            f"  {ev.excerpt[:400]}\n"
            f"  출처: {ev.canonical_url}\n"
        )
    return "\n".join(parts)


def _synthesize(
    topic: str,
    slug: str,
    run_no: int,
    all_evidence: list[Evidence],
    new_count: int,
    model: str,
    since: str,
) -> str:
    """Call Claude CLI to synthesize evidence into a report."""
    if not all_evidence:
        return "수집된 evidence가 없습니다."

    context = _build_evidence_context(all_evidence)
    user_prompt = SYNTHESIS_USER_PROMPT.format(
        topic=topic,
        since=since,
        run_no=run_no,
        total_evidence=len(all_evidence),
        new_evidence=new_count,
        evidence_context=context,
    )
    full_prompt = f"{SYNTHESIS_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"

    if model not in _ALLOWED_MODELS:
        raise ValueError(f"Model {model!r} not in allowed list")

    result = subprocess.run(
        ["claude", "-p", full_prompt, "--model", model, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI synthesis failed: {result.stderr[:500]}")
    return result.stdout.strip()


def _collect_credibility_ratings(
    evidence_list: list[Evidence],
) -> list[CredibilityRating]:
    """Build CredibilityRating list from tier-3 evidence with credibility data."""
    seen: dict[str, CredibilityRating] = {}
    for ev in evidence_list:
        if ev.tier != 3 or ev.credibility_basis is None:
            continue
        handle = ev.source_handle or ev.source_name or ev.canonical_url
        if handle in seen:
            continue
        cred = ev.credibility_basis
        try:
            rubric = CredibilityRubric(
                identity_verifiability=int(cred.get("identity_verifiability", 0)),
                track_record=int(cred.get("track_record", 0)),
                domain_expertise=int(cred.get("domain_expertise", 0)),
                sourcing_transparency=int(cred.get("sourcing_transparency", 0)),
                bias_disclosure=int(cred.get("bias_disclosure", 0)),
            )
            score = ev.credibility_score or rubric.composite
            seen[handle] = CredibilityRating(
                source_handle=handle,
                source_type=ev.source_type,
                display_name=ev.source_name,
                score=score,
                rubric=rubric,
                rationale=cred.get("rationale", ""),
                evaluated_at=ev.fetched_at,
                evaluator_model="agent-inline",
            )
        except Exception as e:
            logger.warning("Failed to build CredibilityRating for %s: %s", handle, e)
    return list(seen.values())


class IssueTrackOrchestrator:
    def __init__(
        self,
        store: IssueStore | None = None,
        tier_limit: int = 4,
    ) -> None:
        self.store = store or IssueStore()
        self.tier_limit = tier_limit
        self._agents = [
            PrimarySourceAgent(),
            Tier1MediaAgent(),
            SocialBlogAgent(),
            TelegramRecallAgent(),
        ]

    def _get_agents(self):
        return [a for a in self._agents if a.tier <= self.tier_limit]

    async def collect(self, ctx: IssueRunContext) -> list[Evidence]:
        """Run all agents in parallel."""
        tasks = [agent.research(ctx) for agent in self._get_agents()]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_evidence: list[Evidence] = []
        for r in raw_results:
            if isinstance(r, BaseException):
                logger.error("Agent raised exception: %s", r)
            elif isinstance(r, list):
                all_evidence.extend(r)
        return all_evidence

    def run(
        self,
        topic: str,
        slug: str | None = None,
        since: str | None = None,
        model: str = "claude-sonnet-4-6",
        collect_only: bool = False,
        from_evidence: list[Evidence] | None = None,
        output_base: Path | None = None,
    ) -> IssueReport:
        """Full pipeline: collect → dedup/persist → synthesize → render."""
        if slug is None:
            slug = _extract_slug(topic)

        if since is None:
            from datetime import timedelta
            since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")

        seed_keywords = _extract_keywords(topic)

        run_id = _make_run_id()
        started_at = datetime.now(UTC).isoformat()

        run = IssueRun(
            run_id=run_id,
            slug=slug,
            title=topic,
            started_at=started_at,
            model_used=model,
            pipeline_version="1.0",
        )

        with self.store as store:
            store.ensure_topic(slug, topic)
            store.upsert_run(run)

            run_no = store.get_run_count(slug)

            # Collect phase
            if from_evidence is None:
                ctx = IssueRunContext(
                    topic=topic,
                    slug=slug,
                    run_id=run_id,
                    since=since,
                    seed_keywords=seed_keywords,
                )
                raw_evidence = asyncio.run(self.collect(ctx))
            else:
                raw_evidence = from_evidence

            # Dedup + persist
            new_count = 0
            stored: list[Evidence] = []
            for ev in raw_evidence:
                is_new, final_ev = store.upsert_evidence(ev, run_id)
                if is_new:
                    new_count += 1
                stored.append(final_ev)

            # Load all cumulative evidence for this slug
            all_evidence = store.get_evidence_for_slug(slug)

            # Update run stats
            run = run.model_copy(
                update={
                    "total_evidence": len(all_evidence),
                    "new_evidence": new_count,
                }
            )
            store.upsert_run(run)
            store.update_topic_last_run(slug)

            if collect_only:
                return IssueReport(
                    run=run,
                    title=topic,
                    evidence_by_tier={},
                    generated_at=datetime.now(UTC).isoformat(),
                )

            # Synthesize
            synthesis = _synthesize(
                topic=topic,
                slug=slug,
                run_no=run_no,
                all_evidence=all_evidence,
                new_count=new_count,
                model=model,
                since=since,
            )

            # Build evidence_by_tier
            by_tier: dict[int, list[Evidence]] = {}
            for ev in all_evidence:
                by_tier.setdefault(ev.tier, []).append(ev)

            # Collect credibility ratings
            cred_ratings = _collect_credibility_ratings(all_evidence)

            # Render
            output_dir = output_base or (
                Path("reports") / "issue_track" / slug
            )
            report = IssueReport(
                run=run,
                title=topic,
                synthesis=synthesis,
                evidence_by_tier=by_tier,
                credibility_ratings=cred_ratings,
                generated_at=datetime.now(UTC).isoformat(),
            )
            report_path = render_report(report, output_dir, run_no)
            update_index(output_dir, run_no, run_id, new_count, len(all_evidence))

            # Save evidence snapshot
            ev_snapshot_path = output_dir / f"{report_path.stem}-evidence.json"
            ev_snapshot_path.write_text(
                json.dumps(
                    [ev.model_dump() for ev in all_evidence],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            # Update run with report path
            run = run.model_copy(update={"report_path": str(report_path), "finished_at": datetime.now(UTC).isoformat()})
            store.upsert_run(run)
            report = report.model_copy(update={"run": run})

        return report
