"""Separately editable Technical Trader prompts."""

from ._shared import (
    render_backtest_interpretation,
    render_candidate_proposal,
    render_candidate_review,
    render_research_plan,
)
from .compaction import (
    CandidatePromptScope,
    DEFAULT_CANDIDATE_PROMPT_ASSETS,
    MAX_CANDIDATE_PROMPT_ASSETS,
    MIN_CANDIDATE_PROMPT_ASSETS,
    compact_horizon_technical_report,
)
from .technical import TECHNICAL_LENS_REQUIREMENTS, TECHNICAL_TRADER_SYSTEM_PROMPT

__all__ = [
    "CandidatePromptScope",
    "DEFAULT_CANDIDATE_PROMPT_ASSETS",
    "MAX_CANDIDATE_PROMPT_ASSETS",
    "MIN_CANDIDATE_PROMPT_ASSETS",
    "TECHNICAL_LENS_REQUIREMENTS",
    "TECHNICAL_TRADER_SYSTEM_PROMPT",
    "compact_horizon_technical_report",
    "render_backtest_interpretation",
    "render_candidate_proposal",
    "render_candidate_review",
    "render_research_plan",
]
