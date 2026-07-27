"""Collective Risk / Skeptic Agent interface placeholder."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols.research_contracts import RiskReviewRequest, RiskReviewResponse


@runtime_checkable
class RiskAgent(Protocol):
    """Review all settled trader candidates together after backtesting."""

    agent_id: str

    async def review(self, request: RiskReviewRequest) -> RiskReviewResponse:
        """Approve or veto each candidate and record collective critiques."""
