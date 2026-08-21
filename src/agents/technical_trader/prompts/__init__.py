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
    OpportunityBinding,
    assert_no_opportunity_references,
    build_opportunity_prompt_report,
    compact_horizon_technical_report,
    redact_opportunity_references,
)
from .technical import TECHNICAL_LENS_REQUIREMENTS, TECHNICAL_TRADER_SYSTEM_PROMPT

__all__ = [
    "CandidatePromptScope",
    "DEFAULT_CANDIDATE_PROMPT_ASSETS",
    "MAX_CANDIDATE_PROMPT_ASSETS",
    "MIN_CANDIDATE_PROMPT_ASSETS",
    "OpportunityBinding",
    "TECHNICAL_LENS_REQUIREMENTS",
    "TECHNICAL_TRADER_SYSTEM_PROMPT",
    "assert_no_opportunity_references",
    "build_opportunity_prompt_report",
    "compact_horizon_technical_report",
    "redact_opportunity_references",
    "render_backtest_interpretation",
    "render_candidate_proposal",
    "render_candidate_review",
    "render_research_plan",
]
