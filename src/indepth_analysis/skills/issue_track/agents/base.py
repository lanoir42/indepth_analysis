"""Base class and context for Issue Track agents."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from indepth_analysis.models.issue_track import Evidence


@dataclass
class IssueRunContext:
    topic: str
    slug: str
    run_id: str
    since: str  # ISO date string YYYY-MM-DD
    seed_keywords: list[str] = field(default_factory=list)
    language_hint: str = "ko,en"


class IssueAgent(ABC):
    name: str = ""
    tier: int = 0

    @abstractmethod
    async def research(self, ctx: IssueRunContext) -> list[Evidence]:
        """Collect evidence for the given issue context."""
        ...
