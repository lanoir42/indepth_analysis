"""Base class for research agents."""

import logging
from abc import ABC, abstractmethod

from indepth_analysis.models.euro_macro import AgentResult

logger = logging.getLogger(__name__)


class BaseResearchAgent(ABC):
    """Abstract base for all research agents."""

    name: str = ""

    @abstractmethod
    async def research(self, year: int, month: int) -> AgentResult:
        """Run research for the given year/month and return findings."""
        ...
