"""Shared point-in-time Data Service placeholder interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols.research_contracts import DataRequest, DataResponse


@runtime_checkable
class DataService(Protocol):
    """Serve all traders through one provenance-aware data boundary."""

    async def fetch(self, request: DataRequest) -> DataResponse:
        """Return point-in-time artifacts, availability, and provenance."""
