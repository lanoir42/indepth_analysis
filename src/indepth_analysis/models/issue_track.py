"""Data models for the Issue Track skill."""

from typing import Literal

from pydantic import BaseModel


class CredibilityRubric(BaseModel):
    identity_verifiability: int  # 0-5
    track_record: int  # 0-5
    domain_expertise: int  # 0-5
    sourcing_transparency: int  # 0-5
    bias_disclosure: int  # 0-5

    @property
    def composite(self) -> float:
        return round(
            self.identity_verifiability * 0.15
            + self.track_record * 0.25
            + self.domain_expertise * 0.25
            + self.sourcing_transparency * 0.20
            + self.bias_disclosure * 0.15,
            2,
        )


class CredibilityRating(BaseModel):
    source_handle: str
    source_type: str
    display_name: str | None = None
    score: float  # 0.0-5.0
    rubric: CredibilityRubric
    rationale: str
    evaluated_at: str
    evaluator_model: str

    @property
    def label(self) -> str:
        if self.score >= 4.5:
            return "High"
        elif self.score >= 3.5:
            return "Medium-High"
        elif self.score >= 2.5:
            return "Medium"
        elif self.score >= 1.0:
            return "Low"
        return "Reject"


class Evidence(BaseModel):
    evidence_id: str = ""
    slug: str
    tier: int  # 1-4
    source_type: str
    source_name: str | None = None
    source_handle: str | None = None
    canonical_url: str
    title: str | None = None
    excerpt: str
    full_text_hash: str | None = None
    published_at: str | None = None
    fetched_at: str
    language: str | None = None
    stance: Literal["concern", "dissent", "rebuttal", "neutral", "factual"] = "neutral"
    credibility_score: float | None = None
    credibility_basis: dict | None = None
    first_seen_run: str = ""
    last_seen_run: str = ""
    seen_count: int = 1


class IssueRun(BaseModel):
    run_id: str
    slug: str
    title: str
    started_at: str
    finished_at: str | None = None
    model_used: str
    total_evidence: int = 0
    new_evidence: int = 0
    report_path: str | None = None
    pipeline_version: str


class IssueReport(BaseModel):
    run: IssueRun
    title: str
    synthesis: str = ""
    evidence_by_tier: dict[int, list[Evidence]] = {}
    credibility_ratings: list[CredibilityRating] = []
    generated_at: str
