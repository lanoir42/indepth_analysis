"""Data models for the Development & Welfare report skill."""

from pydantic import BaseModel

from indepth_analysis.models.euro_macro import AgentResult, ReportSection


class DevWelfareReport(BaseModel):
    """Final synthesized Development & Welfare report."""

    year: int
    month: int
    week: int | None = None
    title: str
    report_type: str = "weekly"  # weekly, monthly, quarterly
    sections: list[ReportSection] = []
    agent_results: list[AgentResult] = []
    model_used: str = ""
    total_findings: int = 0
    generated_at: str | None = None
