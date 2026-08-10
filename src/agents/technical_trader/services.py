"""Replaceable shared-service interfaces used by the Technical Trader.

Adapters should be expected to change when the shared Data and Backtest
contracts are finalized. Keeping both dependencies behind Protocols isolates
those changes from the Technical Trader's reasoning and local tools.
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
    """Supply the shared horizon-matched held-out window to a trader.

    This boundary deliberately contains no Technical Trader default. The same
    policy can be injected into Technical, Fundamental, and Quant traders. Its
    market calendar must resolve exactly the PM horizon's number of sessions.
    """

    def resolve(
        self,
        *,
        task: TraderTask,
        plan: BacktestPlanDraft,
        data_response: DataResponse,
    ) -> ValidationSplit:
        """Return an exact horizon-sized window no later than ``as_of_date``."""
