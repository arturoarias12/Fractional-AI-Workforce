"""Framework-neutral description of the executable production topology."""

from __future__ import annotations

from dataclasses import dataclass

from .nodes import (
    FUNDAMENTAL_TRADER_NODE,
    MEMORY_READ_NODE,
    MEMORY_WRITE_NODE,
    PLANNED_NODE_IDS,
    PM_DECISION_NODE,
    PM_INTAKE_NODE,
    PREPARE_PM_REVIEW_NODE,
    PREPARE_REPORTING_NODE,
    PREPARE_ROUND_NODE,
    QUANT_TRADER_NODE,
    REPORTING_NODE,
    RISK_NODE,
    TECHNICAL_TRADER_NODE,
    TRADER_JOIN_NODE,
    TRADER_NODE_IDS,
)


@dataclass(frozen=True, slots=True)
class PlannedEdge:
    source: str
    target: str
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class ParallelGroup:
    fan_out_from: str
    branch_nodes: tuple[str, ...]
    join_at: str
    join_policy: str


@dataclass(frozen=True, slots=True)
class WorkflowBlueprint:
    node_ids: tuple[str, ...]
    edges: tuple[PlannedEdge, ...]
    trader_parallel_group: ParallelGroup
    strategy_combination_implemented: bool
    notes: tuple[str, ...]


def planned_workflow() -> WorkflowBlueprint:
    """Describe the topology implemented by :mod:`graph.production`."""

    return WorkflowBlueprint(
        node_ids=PLANNED_NODE_IDS,
        edges=(
            PlannedEdge(MEMORY_READ_NODE, PM_INTAKE_NODE),
            PlannedEdge(PM_INTAKE_NODE, PREPARE_ROUND_NODE),
            PlannedEdge(PREPARE_ROUND_NODE, TECHNICAL_TRADER_NODE),
            PlannedEdge(PREPARE_ROUND_NODE, FUNDAMENTAL_TRADER_NODE),
            PlannedEdge(PREPARE_ROUND_NODE, QUANT_TRADER_NODE),
            PlannedEdge(TECHNICAL_TRADER_NODE, TRADER_JOIN_NODE),
            PlannedEdge(FUNDAMENTAL_TRADER_NODE, TRADER_JOIN_NODE),
            PlannedEdge(QUANT_TRADER_NODE, TRADER_JOIN_NODE),
            PlannedEdge(TRADER_JOIN_NODE, RISK_NODE),
            PlannedEdge(
                RISK_NODE,
                PREPARE_REPORTING_NODE,
                condition="risk_review_completed",
            ),
            PlannedEdge(
                RISK_NODE,
                PREPARE_PM_REVIEW_NODE,
                condition="risk_unavailable_or_failed",
            ),
            PlannedEdge(PREPARE_REPORTING_NODE, REPORTING_NODE),
            PlannedEdge(REPORTING_NODE, PREPARE_PM_REVIEW_NODE),
            PlannedEdge(PREPARE_PM_REVIEW_NODE, PM_DECISION_NODE),
            PlannedEdge(PM_DECISION_NODE, MEMORY_WRITE_NODE),
            PlannedEdge(
                MEMORY_WRITE_NODE,
                MEMORY_READ_NODE,
                condition="pm_requested_another_round",
            ),
        ),
        trader_parallel_group=ParallelGroup(
            fan_out_from=PREPARE_ROUND_NODE,
            branch_nodes=TRADER_NODE_IDS,
            join_at=TRADER_JOIN_NODE,
            join_policy="wait_until_all_active_branches_settle",
        ),
        strategy_combination_implemented=False,
        notes=(
            "Only active trader branches invoke their injected agent node.",
            "A trader failure is preserved and does not erase other packages.",
            "Risk reviews the settled batch collectively.",
            "Risk or Reporting failure escalates to the PM decision interrupt.",
            "DataService and BacktestEngine are dependencies, not agent nodes.",
            "Memory supplies controlled context to a later PM round.",
        ),
    )
