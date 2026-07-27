"""Human Portfolio Manager management boundary.

This is a future application/UI integration point, not a hireable specialist
agent and not an autonomous strategy-selection implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols.research_contracts import PMDecision, PMMandate


@runtime_checkable
class PortfolioManagerGateway(Protocol):
    """Interface the future PM application should provide."""

    async def create_mandate(self) -> PMMandate:
        """Collect and normalize one human-authored research mandate."""

    async def decide(self, reporting_output_id: str) -> PMDecision:
        """Record the human PM's select, reject, or another-round decision."""
