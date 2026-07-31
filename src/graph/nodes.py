"""Stable node identities and injectable graph-node boundaries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeAlias


MEMORY_READ_NODE = "memory_read"
PM_INTAKE_NODE = "pm_intake"
PREPARE_ROUND_NODE = "prepare_round"
TECHNICAL_TRADER_NODE = "technical_trader"
FUNDAMENTAL_TRADER_NODE = "fundamental_trader"
QUANT_TRADER_NODE = "quant_trader"
TRADER_JOIN_NODE = "trader_join"
RISK_NODE = "risk_collective_review"
PREPARE_REPORTING_NODE = "prepare_reporting"
REPORTING_NODE = "reporting"
PREPARE_PM_REVIEW_NODE = "prepare_pm_review"
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
    PREPARE_ROUND_NODE,
    *TRADER_NODE_IDS,
    TRADER_JOIN_NODE,
    RISK_NODE,
    PREPARE_REPORTING_NODE,
    REPORTING_NODE,
    PREPARE_PM_REVIEW_NODE,
    PM_DECISION_NODE,
    MEMORY_WRITE_NODE,
)


GraphNodeResult: TypeAlias = (
    Mapping[str, Any] | Awaitable[Mapping[str, Any]]
)
GraphNode: TypeAlias = Callable[
    [Mapping[str, Any]],
    GraphNodeResult,
]


__all__ = [
    "FUNDAMENTAL_TRADER_NODE",
    "GraphNode",
    "GraphNodeResult",
    "MEMORY_READ_NODE",
    "MEMORY_WRITE_NODE",
    "PLANNED_NODE_IDS",
    "PM_DECISION_NODE",
    "PM_INTAKE_NODE",
    "PREPARE_PM_REVIEW_NODE",
    "PREPARE_REPORTING_NODE",
    "PREPARE_ROUND_NODE",
    "QUANT_TRADER_NODE",
    "REPORTING_NODE",
    "RISK_NODE",
    "TECHNICAL_TRADER_NODE",
    "TRADER_JOIN_NODE",
    "TRADER_NODE_IDS",
]
