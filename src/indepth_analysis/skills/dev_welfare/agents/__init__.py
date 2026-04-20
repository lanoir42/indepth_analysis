"""Development & Welfare research agents."""

from indepth_analysis.skills.dev_welfare.agents.journal_agent import JournalAgent
from indepth_analysis.skills.dev_welfare.agents.kihasa_agent import KIHASAAgent
from indepth_analysis.skills.dev_welfare.agents.koica_agent import KOICAAgent
from indepth_analysis.skills.dev_welfare.agents.legislation_agent import (
    LegislationAgent,
)
from indepth_analysis.skills.dev_welfare.agents.media_agent import DevWelfareMediaAgent
from indepth_analysis.skills.dev_welfare.agents.oecd_agent import OECDAgent

__all__ = [
    "KOICAAgent",
    "KIHASAAgent",
    "LegislationAgent",
    "JournalAgent",
    "DevWelfareMediaAgent",
    "OECDAgent",
]
