"""Replaceable shared-service interfaces used by the Quant Trader.

Mirrors the Technical Trader's service boundary so the same DataService,
BacktestEngine, and ValidationSplitPolicy implementations can be injected
into all three traders once the shared services are finalized.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols import (
    BacktestPlanDraft,
    BacktestRequest,
    BacktestResult,
    DataRequest,
    DataResponse,
    TraderTask,
    ValidationSplit,
)


@runtime_checkable
class DataService(Protocol):
    async def fetch(self, request: DataRequest) -> DataResponse:
        """Return point-in-time data and provenance for a trader request."""


@runtime_checkable
class BacktestEngine(Protocol):
    async def run(self, request: BacktestRequest) -> BacktestResult:
        """Evaluate a candidate using deterministic code."""


@runtime_checkable
class ValidationSplitPolicy(Protocol):
    """Supply the shared fixed held-out window to a trader.

    Contains no Quant Trader default - the same policy instance can be
    shared with Technical and Fundamental so every trader is scored
    against the exact same train/test boundary.
    """

    def resolve(
        self,
        *,
        task: TraderTask,
        plan: BacktestPlanDraft,
        data_response: DataResponse,
    ) -> ValidationSplit:
        """Return a deterministic window ending no later than ``as_of_date``."""
