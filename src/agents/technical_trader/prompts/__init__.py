"""Separately editable Technical Trader prompts."""

from ._shared import (
    render_backtest_interpretation,
    render_candidate_proposal,
    render_research_plan,
)
from .technical import TECHNICAL_LENS_REQUIREMENTS, TECHNICAL_TRADER_SYSTEM_PROMPT

__all__ = [
    "TECHNICAL_LENS_REQUIREMENTS",
    "TECHNICAL_TRADER_SYSTEM_PROMPT",
    "render_backtest_interpretation",
    "render_candidate_proposal",
    "render_research_plan",
]
