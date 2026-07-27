"""Structural interfaces shared by future specialist implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols.research_contracts import (
    PMMandate,
    SpecialistId,
    TaskLineage,
    TraderStrategyPackage,
)


@runtime_checkable
class TraderAgent(Protocol):
    """Common interface for the three independent trader branches."""

    agent_id: SpecialistId

    async def run(
        self,
        mandate: PMMandate,
        lineage: TaskLineage,
    ) -> TraderStrategyPackage:
        """Return one complete, partial, or failed candidate package."""
