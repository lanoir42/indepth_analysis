"""Markdown renderer for Issue Track reports."""

from datetime import UTC, datetime
from pathlib import Path

from indepth_analysis.models.issue_track import CredibilityRating, Evidence, IssueReport


def render_report(
    report: IssueReport,
    output_dir: Path,
    run_no: int,
) -> Path:
    """Render report to markdown file and return path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    filename = f"{date_str}-run{run_no}.md"
    path = output_dir / filename

    lines: list[str] = []

    # Header
    lines.append(f"# [{datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC] {report.title}")
    lines.append("")

    # Meta block
    lines.append("## 0. 메타")
    lines.append(f"- **slug**: `{report.run.slug}`")
    lines.append(f"- **run**: #{run_no} / run_id: `{report.run.run_id}`")
    lines.append(
        f"- **누적 evidence**: {report.run.total_evidence}건 "
        f"(이번 신규 {report.run.new_evidence}건)"
    )
    lines.append(f"- **모델**: {report.run.model_used}")
    lines.append(f"- **파이프라인**: v{report.run.pipeline_version}")
    lines.append("")

    # Synthesis body
    if report.synthesis:
        lines.append(report.synthesis)
        lines.append("")

    # Evidence summary by tier
    lines.append("---")
    lines.append("")
    lines.append("## Evidence 요약")
    for tier in sorted(report.evidence_by_tier.keys()):
        tier_label = {
            1: "1차 자료",
            2: "주요 매체",
            3: "소셜·블로그",
            4: "Telegram",
        }.get(tier, f"Tier {tier}")
        ev_list = report.evidence_by_tier[tier]
        lines.append(f"### Tier {tier} — {tier_label} ({len(ev_list)}건)")
        for ev in ev_list[:20]:  # Cap display at 20 per tier
            stance_badge = f"[{ev.stance}]"
            cred_badge = (
                f" [cred: {ev.credibility_score:.1f}/5]"
                if ev.credibility_score is not None and tier == 3
                else ""
            )
            title = ev.title or ev.canonical_url[:80]
            lines.append(f"- **{title}** {stance_badge}{cred_badge}")
            if ev.source_name:
                lines.append(f"  - 출처: {ev.source_name}")
            lines.append(f"  - URL: {ev.canonical_url}")
        lines.append("")

    # Credibility appendix
    if report.credibility_ratings:
        lines.append("---")
        lines.append("")
        lines.append("## 부록 A. 소셜미디어 출처 신뢰도 평가")
        lines.append("")

        # Summary table
        lines.append("| Handle | Type | Display | Score | 라벨 | 근거 요약 |")
        lines.append("|---|---|---|---|---|---|")
        for cr in report.credibility_ratings:
            lines.append(
                f"| {cr.source_handle} | {cr.source_type} | "
                f"{cr.display_name or '-'} | {cr.score:.1f} | "
                f"{cr.label} | {cr.rationale[:60]}… |"
            )
        lines.append("")

        # Detailed rubric table
        lines.append("**축별 세부 점수**")
        lines.append("")
        lines.append(
            "| Handle | identity | track_record | expertise | sourcing | bias | composite |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for cr in report.credibility_ratings:
            r = cr.rubric
            lines.append(
                f"| {cr.source_handle} | {r.identity_verifiability} | "
                f"{r.track_record} | {r.domain_expertise} | "
                f"{r.sourcing_transparency} | {r.bias_disclosure} | "
                f"**{r.composite:.2f}** |"
            )
        lines.append("")

    lines.append(f"*Generated at {report.generated_at}*")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def update_index(output_dir: Path, run_no: int, run_id: str, new_evidence: int, total_evidence: int) -> None:
    """Append run entry to INDEX.md."""
    index_path = output_dir / "INDEX.md"
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    if not index_path.exists():
        header = f"# Issue Track — {output_dir.name}\n\n| Run | 날짜 | run_id | 신규 | 누적 |\n|---|---|---|---|---|\n"
        index_path.write_text(header, encoding="utf-8")

    with index_path.open("a", encoding="utf-8") as f:
        f.write(f"| #{run_no} | {now} | `{run_id[:8]}` | {new_evidence} | {total_evidence} |\n")
