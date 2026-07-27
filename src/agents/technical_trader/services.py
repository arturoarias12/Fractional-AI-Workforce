"""Provisional shared-service interfaces; neither service is implemented here.

Adapters should be expected to change when the shared Data and Backtest
contracts are finalized. Keeping both dependencies behind Protocols isolates
those changes from the Technical Trader's reasoning and local tools.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models.backtest import BacktestRequest, BacktestResult
from .models.data import DataRequest, DataResponse


@runtime_checkable
class DataService(Protocol):
    async def fetch(self, request: DataRequest) -> DataResponse:
        """Return point-in-time data and provenance for a trader request."""


@runtime_checkable
class BacktestEngine(Protocol):
    async def run(self, request: BacktestRequest) -> BacktestResult:
        """Evaluate a candidate using deterministic code."""
