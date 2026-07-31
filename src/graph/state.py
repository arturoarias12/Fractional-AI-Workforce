"""Typed, checkpoint-safe state for the production research workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Required, TypedDict

JsonMapping = dict[str, Any]


def merge_mappings(
    left: Mapping[str, Any] | None,
    right: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Associatively merge branch-isolated updates from parallel nodes."""

    merged = dict(left or {})
    merged.update(right or {})
    return merged


def append_events(
    left: tuple[JsonMapping, ...] | None,
    right: tuple[JsonMapping, ...] | None,
) -> tuple[JsonMapping, ...]:
    """Append immutable operational events without mutating prior state."""

    return (*tuple(left or ()), *tuple(right or ()))


class TraderBranchState(TypedDict, total=False):
    trader_id: str
    active: bool
    lineage: JsonMapping
    status: str
    package: JsonMapping
    failures: tuple[JsonMapping, ...]


class WorkflowInput(TypedDict, total=False):
    """Minimal input accepted by the top-level graph."""

    pm_mandate: Required[JsonMapping]
    active_specialists: tuple[str, ...]
    run_id: str
    canonical_universe_id: str | None
    evaluation_policy_id: str | None


class WorkflowState(TypedDict, total=False):
    """Shared graph state.

    Large datasets, ledger contents, and reports stay outside the checkpoint;
    this state carries validated contracts or JSON-compatible references.
    """

    workflow_id: str
    run_id: str
    round_number: int
    max_rounds: int
    as_of_date: str
    pm_mandate: JsonMapping
    active_specialists: tuple[str, ...]
    memory_context: JsonMapping | None

    technical_trader_package: JsonMapping | None
    fundamental_trader_package: JsonMapping | None
    quant_trader_package: JsonMapping | None
    trader_branches: Annotated[dict[str, TraderBranchState], merge_mappings]
    trader_packages: dict[str, JsonMapping]

    round_audit_summary_reference: str | None
    provenance_record_ids: tuple[str, ...]
    candidate_memo_references: dict[str, str]
    round_history_reference: str | None
    canonical_universe_id: str | None
    evaluation_policy_id: str | None

    risk_review_request: JsonMapping | None
    risk_review_response: JsonMapping | None
    risk_failure: JsonMapping | None
    surviving_candidate_ids: tuple[str, ...]

    reporting_request: JsonMapping | None
    reporting_output: JsonMapping | None
    reporting_failure: JsonMapping | None

    pm_decision: JsonMapping | None
    pending_human_action: JsonMapping | None
    memory_record_id: str | None

    agent_lifecycle: Annotated[
        dict[str, JsonMapping],
        merge_mappings,
    ]
    operational_events: Annotated[
        tuple[JsonMapping, ...],
        append_events,
    ]
    cancellation_requested: bool


__all__ = [
    "TraderBranchState",
    "WorkflowInput",
    "WorkflowState",
    "append_events",
    "merge_mappings",
]
