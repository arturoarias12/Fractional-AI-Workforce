"""Reporting Agent interface placeholder."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols.research_contracts import ReportingOutput, ReportingRequest


@runtime_checkable
class ReportingAgent(Protocol):
    """Document and compare Risk survivors without combining strategies."""

    agent_id: str

    async def report(self, request: ReportingRequest) -> ReportingOutput:
        """Return a PM-facing memo for the surviving candidates."""
