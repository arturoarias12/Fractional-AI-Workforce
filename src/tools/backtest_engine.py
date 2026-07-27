"""Shared deterministic Backtest Engine placeholder interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols.research_contracts import BacktestRequest, BacktestResult


@runtime_checkable
class BacktestEngine(Protocol):
    """Execute every trader candidate under common coded assumptions."""

    async def run(self, request: BacktestRequest) -> BacktestResult:
        """Return reproducible metrics; an LLM may not manufacture them."""
