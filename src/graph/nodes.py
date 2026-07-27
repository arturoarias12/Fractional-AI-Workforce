"""Node identities and structural callable boundary.

Concrete nodes are intentionally absent until their owners provide adapters.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import Any, Protocol


MEMORY_READ_NODE = "memory_read"
PM_INTAKE_NODE = "pm_intake"
TECHNICAL_TRADER_NODE = "technical_trader"
FUNDAMENTAL_TRADER_NODE = "fundamental_trader"
QUANT_TRADER_NODE = "quant_trader"
RISK_NODE = "risk_collective_review"
REPORTING_NODE = "reporting"
PM_DECISION_NODE = "pm_decision"
MEMORY_WRITE_NODE = "memory_write"

TRADER_NODE_IDS: tuple[str, ...] = (
    TECHNICAL_TRADER_NODE,
    FUNDAMENTAL_TRADER_NODE,
    QUANT_TRADER_NODE,
)

PLANNED_NODE_IDS: tuple[str, ...] = (
    MEMORY_READ_NODE,
    PM_INTAKE_NODE,
    *TRADER_NODE_IDS,
    RISK_NODE,
    REPORTING_NODE,
    PM_DECISION_NODE,
    MEMORY_WRITE_NODE,
)


class GraphNode(Protocol):
    async def __call__(
        self,
        state: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Return a state update without mutating the input mapping."""
