"""External round-to-round Memory service placeholder interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from protocols.research_contracts import MemoryContext, MemoryRecord


@runtime_checkable
class MemoryStore(Protocol):
    """Persist research lessons without acting as a hireable LLM agent."""

    async def load_context(self, workflow_id: str) -> MemoryContext:
        """Return controlled context for a later PM research round."""

    async def record(self, record: MemoryRecord) -> str:
        """Persist results, critiques, the PM decision, and lessons."""
