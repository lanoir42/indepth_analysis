"""Data models for the Euro Macro report skill."""

from pydantic import BaseModel


class ResearchFinding(BaseModel):
    """Single research finding from any agent."""

    title: str
    summary: str
    source_url: str | None = None
    source_name: str = ""
    published_date: str | None = None
    relevance_score: float = 0.0
    category: str = ""


class AgentResult(BaseModel):
    """Output from one research agent."""

    agent_name: str
    findings: list[ResearchFinding] = []
    search_queries: list[str] = []
    error: str | None = None


class ReportSection(BaseModel):
    """A section within the synthesized report."""

    heading: str
    content: str


class EuroMacroReport(BaseModel):
    """Final synthesized Euro Macro report."""

    year: int
    month: int
    title: str
    sections: list[ReportSection] = []
    agent_results: list[AgentResult] = []
    model_used: str = ""
    total_findings: int = 0
    generated_at: str | None = None
