"""Collective Risk / Skeptic Agent interface placeholder.

The implementation remains with the Risk workstream. This boundary now
reflects the current three-trader review: one request contains the settled
batch plus immutable audit/provenance references, and one response contains
candidate and round-level checklist results.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols.research_contracts import RiskReviewRequest, RiskReviewResponse


@runtime_checkable
class RiskAgent(Protocol):
    """Review the settled trader batch without recomputing engine evidence."""

    agent_id: str

    async def review(self, request: RiskReviewRequest) -> RiskReviewResponse:
        """Return grounded PASS/FLAG/VETO checks and candidate verdicts."""
