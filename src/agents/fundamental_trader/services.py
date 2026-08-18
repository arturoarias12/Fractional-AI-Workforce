"""Replaceable shared-service interfaces used by the Fundamental Trader.

Mirrors Technical and Quant Trader's service boundary so the same
DataService, BacktestEngine, and ValidationSplitPolicy implementations can
be injected into all three traders once the shared services are finalized.
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
        """Return point-in-time data and provenance for a trader request.

        Fundamental Trader issues two categories of request against this
        same protocol: ``PRICE_VOLUME`` (for backtesting the eventual rule)
        and ``ETF_METADATA`` (category / fund family, used to derive the
        ISSUER_SCALE_TIER heuristic - see ``rule_generator.py``).
        """


@runtime_checkable
class BacktestEngine(Protocol):
    async def run(self, request: BacktestRequest) -> BacktestResult:
        """Evaluate a candidate using deterministic code."""


@runtime_checkable
class ValidationSplitPolicy(Protocol):
    """Supply the shared fixed held-out window to a trader.

    Contains no Fundamental Trader default - the same policy instance can
    be shared with Technical and Quant so every trader is scored against
    the exact same train/test boundary.
    """

    def resolve(
        self,
        *,
        task: TraderTask,
        plan: BacktestPlanDraft,
        data_response: DataResponse,
    ) -> ValidationSplit:
        """Return a deterministic window ending no later than ``as_of_date``."""
