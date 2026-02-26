"""Euro Macro research agents."""

from indepth_analysis.skills.euro_macro.agents.data_agent import DataAgent
from indepth_analysis.skills.euro_macro.agents.institutional_agent import (
    InstitutionalAgent,
)
from indepth_analysis.skills.euro_macro.agents.kcif_agent import KCIFAgent
from indepth_analysis.skills.euro_macro.agents.media_agent import MediaAgent

__all__ = ["KCIFAgent", "MediaAgent", "InstitutionalAgent", "DataAgent"]
