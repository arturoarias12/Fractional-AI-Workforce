"""Replaceable structural interfaces shared by trader implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols import SpecialistId, TraderStrategyPackage, TraderTask


@runtime_checkable
class TraderAgent(Protocol):
    """Common interface for the three independent trader branches.

    Ordinary analytical or dependency failures are returned as settled
    packages. Cancellation may still propagate to orchestration.
    """

    trader_id: SpecialistId

    async def run(self, request: TraderTask) -> TraderStrategyPackage:
        """Return one complete, partial, or failed candidate package."""
