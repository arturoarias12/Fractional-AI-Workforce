"""LangGraph-friendly state placeholders for the planned research loop."""

from __future__ import annotations

from typing import TypedDict

from protocols.events import OperationalEvent
from protocols.research_contracts import (
    MemoryContext,
    PMDecision,
    PMMandate,
    ReportingOutput,
    RiskReviewRequest,
    RiskReviewResponse,
    RunStatus,
    SpecialistId,
    TaskLineage,
    TraderFailure,
    TraderStrategyPackage,
)


class TraderBranchState(TypedDict, total=False):
    trader_id: SpecialistId
    lineage: TaskLineage
    status: RunStatus
    package: TraderStrategyPackage
    failures: tuple[TraderFailure, ...]


class WorkflowState(TypedDict, total=False):
    """Transport-neutral state; final serialization remains to be confirmed."""

    workflow_id: str
    round_number: int
    as_of_date: str
    pm_mandate: PMMandate
    active_specialists: tuple[SpecialistId, ...]
    memory_context: MemoryContext
    trader_branches: dict[str, TraderBranchState]
    trader_packages: dict[str, TraderStrategyPackage]
    risk_review_request: RiskReviewRequest
    risk_review_response: RiskReviewResponse
    surviving_candidate_ids: tuple[str, ...]
    reporting_output: ReportingOutput
    pm_decision: PMDecision
    memory_record_id: str
    operational_events: tuple[OperationalEvent, ...]
    cancellation_requested: bool
